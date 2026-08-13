from __future__ import annotations

import argparse
import calendar
import ctypes
import ctypes.wintypes
import inspect
import os
import sqlite3
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

import flet as ft

from backup_service import (
    BackupError,
    BackupSummary,
    default_backup_name,
    export_workspace,
    inspect_backup,
    restore_workspace,
)
from database import Database
from markdown_store import MarkdownStore


if os.name == "nt":
    try:
        # Keep QA capture coordinates in physical pixels on scaled Windows
        # desktops; this does not alter Flet's own DPI-aware rendering.
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "entp_manual.db"
RUNTIME_ERROR_LOG = ROOT / "logs" / "runtime-errors.log"

BLUE = "#316BEE"
BLUE_DARK = "#2457CC"
BLUE_SOFT = "#EEF3FF"
INK = "#171A21"
MUTED = "#737986"
LINE = "#E7E9EE"
SURFACE = "#FFFFFF"
SIDEBAR = "#F7F8FB"
CANVAS = "#FBFCFE"
GREEN = "#37A46A"
GREEN_SOFT = "#EAF7EF"
AMBER = "#B87818"
AMBER_SOFT = "#FFF6DF"
RED = "#E45959"


def rounded(radius: int = 18) -> ft.RoundedRectangleBorder:
    return ft.RoundedRectangleBorder(radius=radius)


def pill(text: str, *, color: str = BLUE, bgcolor: str = BLUE_SOFT, icon=None) -> ft.Container:
    items: list[ft.Control] = []
    if icon is not None:
        items.append(ft.Icon(icon, size=15, color=color))
    items.append(ft.Text(text, size=13, weight=ft.FontWeight.W_600, color=color))
    return ft.Container(
        content=ft.Row(items, spacing=6, tight=True),
        padding=ft.Padding.symmetric(horizontal=11, vertical=6),
        bgcolor=bgcolor,
        border_radius=99,
    )


def section_title(title: str, subtitle: str = "") -> ft.Row:
    controls: list[ft.Control] = [
        ft.Text(title, size=20, weight=ft.FontWeight.W_700, color=INK)
    ]
    if subtitle:
        controls.append(ft.Text(subtitle, size=13, color=MUTED))
    return ft.Row(controls, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)


class EntpFletApp:
    """Flet UI shell; the existing Database remains the single source of truth."""

    NAV_CURRENT = 0
    NAV_VAULT = 1
    NAV_IDEAS = 2
    NAV_TODAY = 3
    NAV_CALENDAR = 4

    def __init__(self, page: ft.Page, db_path: Path, initial_view: str = "current") -> None:
        self.page = page
        self._closed = False
        self._original_page_update = page.update
        self.page.update = self._protected_page_update
        self.file_picker = ft.FilePicker()
        self.page.services.append(self.file_picker)
        self.db = Database(db_path)
        markdown_root = (
            ROOT / "markdown"
            if db_path.resolve() == DEFAULT_DB.resolve()
            else db_path.parent / f"{db_path.stem}-markdown"
        )
        self.markdown = MarkdownStore(markdown_root)
        self._sync_markdown(show_error=False)
        self.current_mid = self.db.current_mainline_id()
        self.today = date.today()
        self._observed_local_day = self.today
        self.selected_day = self.today
        self.calendar_month = self.today.replace(day=1)
        self.calendar_selected_day = self.today
        self.today_priority_sort = False
        self.today_collapsed: dict[str, bool] = {}
        self.active_index = self.NAV_CURRENT

        self.current_header = ft.Column(spacing=0)
        self.focus_holder = ft.Container()
        self.task_holder = ft.Column(
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.calendar_holder = ft.Container()
        self.detail_holder = ft.Container()
        self.selected_task_id: int | None = None
        self.selected_thought_id: int | None = None
        self.selected_mainline_id: int | None = None
        self.inspiration_capture_open = False
        self.inline_inspiration_input = ft.TextField(
            hint_text="记下灵感，按回车收起",
            hint_style=ft.TextStyle(size=15, color="#A9ADB6"),
            prefix_icon=ft.Icons.LIGHTBULB_OUTLINE_ROUNDED,
            border=ft.InputBorder.NONE,
            filled=True,
            fill_color=AMBER_SOFT,
            text_size=15,
            height=52,
            content_padding=ft.Padding.symmetric(horizontal=7, vertical=12),
            on_submit=self.quick_capture_inspiration,
        )
        self.idea_board_control: ft.Control | None = None
        self.quick_idea_input = ft.TextField(
            hint_text="记下一闪而过的想法…",
            hint_style=ft.TextStyle(size=16, color="#A9ADB6"),
            prefix_icon=ft.Icons.ADD_ROUNDED,
            border=ft.InputBorder.NONE,
            filled=True,
            fill_color=SURFACE,
            text_size=16,
            height=58,
            content_padding=ft.Padding.symmetric(horizontal=8, vertical=14),
            on_submit=self.quick_add_idea,
        )
        self.quick_task_input = ft.TextField(
            hint_text="添加任务",
            hint_style=ft.TextStyle(size=17, color="#B4B7BE"),
            prefix_icon=ft.Icons.ADD_ROUNDED,
            border=ft.InputBorder.NONE,
            filled=True,
            fill_color=SURFACE,
            bgcolor=SURFACE,
            content_padding=ft.Padding.symmetric(horizontal=8, vertical=15),
            text_size=17,
            height=60,
            on_submit=self.quick_add_task,
        )
        self.quick_task_box = ft.Container(
            content=ft.Row(
                [
                    ft.Container(self.quick_task_input, expand=True),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.CALENDAR_MONTH_ROUNDED, size=20, color=BLUE),
                                ft.Text("今天", size=16, color=BLUE),
                                ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED, size=21, color=MUTED),
                            ],
                            spacing=7,
                            tight=True,
                        ),
                        width=104,
                    ),
                ],
                spacing=8,
            ),
            padding=ft.Padding.only(left=8, right=18),
            height=64,
            bgcolor=SURFACE,
            border=ft.Border.all(1, LINE),
            border_radius=16,
        )
        self.quick_task_input.on_focus = lambda _: self._set_quick_input_focus_style(True)
        self.quick_task_input.on_blur = lambda _: self._set_quick_input_focus_style(False)
        self.quick_today_input = ft.TextField(
            hint_text='添加“今天”的任务至“收集箱”',
            hint_style=ft.TextStyle(size=16, color="#A9ADB6"),
            prefix_icon=ft.Icons.ADD_ROUNDED,
            border=ft.InputBorder.NONE,
            filled=True,
            fill_color="#F4F6F9",
            text_size=16,
            height=62,
            content_padding=ft.Padding.symmetric(horizontal=9, vertical=14),
            on_submit=self.quick_add_today_task,
        )
        self.vault_holder = ft.Column(spacing=16)

        self._configure_page()
        self.content_switcher = ft.AnimatedSwitcher(
            content=ft.Container(),
            duration=180,
            reverse_duration=120,
            transition=ft.AnimatedSwitcherTransition.FADE,
            switch_in_curve=ft.AnimationCurve.EASE_OUT,
            switch_out_curve=ft.AnimationCurve.EASE_IN,
            expand=True,
        )
        self.rail = self._build_rail()
        self.page.add(
            ft.Row(
                [
                    ft.Container(
                        self.rail,
                        width=236,
                        bgcolor=SIDEBAR,
                        border=ft.Border.only(right=ft.BorderSide(1, LINE)),
                    ),
                    ft.Container(
                        self.content_switcher,
                        expand=True,
                        bgcolor=CANVAS,
                    ),
                ],
                spacing=0,
                expand=True,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            )
        )
        initial_views = {
            "current": self.NAV_CURRENT,
            "vault": self.NAV_VAULT,
            "ideas": self.NAV_IDEAS,
            "today": self.NAV_TODAY,
            "calendar": self.NAV_CALENDAR,
        }
        self.show_view(initial_views.get(initial_view, self.NAV_CURRENT))

    def _configure_page(self) -> None:
        self.page.title = "ENTP 自强手册 2.0"
        self.page.padding = 0
        self.page.bgcolor = CANVAS
        self.page.enable_screenshots = True
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.on_error = self._handle_page_error
        self.page.on_close = self._wrap_event_handler(
            self._handle_page_closed,
            "关闭页面时释放数据库失败",
        )
        self.page.on_disconnect = self._wrap_event_handler(
            self._handle_page_closed,
            "页面断开时释放数据库失败",
        )
        self.page.window.prevent_close = True
        self.page.window.on_event = self._wrap_event_handler(
            self._handle_window_event,
            "处理窗口事件失败",
        )
        # Let the OS provide the real DPI-aware work area. Explicitly requesting
        # a 1440-DIP window on a scaled Windows desktop makes the right side land
        # off-screen even though Flet reports a wide viewport.
        self.page.window.maximized = True
        self.page.window.min_width = 780
        self.page.window.min_height = 620
        self.page.theme = ft.Theme(
            color_scheme_seed=BLUE,
            font_family="Microsoft YaHei UI",
            visual_density=ft.VisualDensity.COMFORTABLE,
        )

    @staticmethod
    def _write_runtime_error(context: str, details: str) -> None:
        try:
            RUNTIME_ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
            with RUNTIME_ERROR_LOG.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {context}\n{details.rstrip()}\n\n")
        except OSError:
            pass

    def _notify_error(self, message: str) -> None:
        try:
            self.page.show_dialog(
                ft.SnackBar(
                    content=ft.Text(message, size=14),
                    bgcolor="#3A2530",
                    duration=5000,
                )
            )
        except Exception:
            self._write_runtime_error("无法显示错误提示", traceback.format_exc())

    def _notify_success(self, message: str) -> None:
        try:
            self.page.show_dialog(
                ft.SnackBar(
                    content=ft.Text(message, size=14),
                    bgcolor="#254D38",
                    duration=6500,
                )
            )
        except Exception:
            self._write_runtime_error("无法显示成功提示", traceback.format_exc())

    def _sync_markdown(self, *, show_error: bool = True) -> bool:
        try:
            self.markdown.sync_all(self.db)
            return True
        except Exception as error:
            self._write_runtime_error("Markdown 同步失败", traceback.format_exc())
            if show_error:
                self._notify_error(
                    f"数据已经保存，但 Markdown 文档同步失败：{error}。旧文档仍然保留。"
                )
            return False

    def _handle_page_error(self, event) -> None:
        details = str(getattr(event, "data", "") or "未知运行期错误")
        self._write_runtime_error("Flet 运行期回调异常", details)
        if "database is locked" in details.lower():
            message = "数据库暂时被其他程序占用，本次操作没有完成。请稍后再试。"
        else:
            message = "这次操作没有完成，错误已经记录；当前窗口可以继续使用。"
        self._notify_error(message)

    @staticmethod
    def _control_label(control: ft.Control, event_name: str) -> str:
        values = getattr(control, "_values", {})
        for key in ("tooltip", "label", "content", "value"):
            value = values.get(key)
            if isinstance(value, str) and value.strip():
                return f"{type(control).__name__}「{value.strip()[:40]}」.{event_name}"
        return f"{type(control).__name__}.{event_name}"

    @staticmethod
    def _interaction_error_message(error: Exception) -> str:
        if isinstance(error, BackupError):
            return str(error)
        if isinstance(error, sqlite3.OperationalError):
            if "locked" in str(error).lower():
                return "数据库暂时被占用，本次操作没有保存，请稍后重试"
            return f"数据库操作没有完成：{error}"
        if isinstance(error, PermissionError):
            return "文件正在被占用或没有访问权限，本次操作没有完成"
        if isinstance(error, OSError):
            return f"文件操作没有完成：{error}"
        if isinstance(error, ValueError) and str(error).strip():
            return str(error)
        return "这次操作没有完成；当前窗口仍可继续使用，请重试或切换页面确认状态"

    def _report_interaction_error(
        self,
        context: str,
        error: Exception,
        message: str | None = None,
        details: str | None = None,
    ) -> None:
        original_details = details or traceback.format_exc()
        try:
            if hasattr(self, "db") and self.db.conn.in_transaction:
                self.db.conn.rollback()
        except Exception:
            self._write_runtime_error(
                f"{context}；回滚未完成事务失败",
                traceback.format_exc(),
            )
        self._write_runtime_error(context, original_details)
        self._notify_error(message or self._interaction_error_message(error))

    def _interaction_state_snapshot(self) -> dict[str, object]:
        names = (
            "active_index",
            "current_mid",
            "selected_task_id",
            "selected_thought_id",
            "selected_mainline_id",
            "selected_day",
            "calendar_month",
            "calendar_selected_day",
            "inspiration_capture_open",
            "today_priority_sort",
        )
        snapshot: dict[str, object] = {}
        for name in names:
            try:
                if hasattr(self, name):
                    snapshot[name] = getattr(self, name)
            except Exception:
                self._write_runtime_error(
                    f"创建交互快照失败：{name}",
                    traceback.format_exc(),
                )
        try:
            if hasattr(self, "today_collapsed"):
                snapshot["today_collapsed"] = dict(self.today_collapsed)
            if hasattr(self, "rail"):
                snapshot["_rail_selected_index"] = self.rail.selected_index
        except Exception:
            self._write_runtime_error("创建交互快照失败", traceback.format_exc())
        return snapshot

    def _restore_interaction_state(self, snapshot: dict[str, object]) -> None:
        for name, value in snapshot.items():
            try:
                if name == "_rail_selected_index" and hasattr(self, "rail"):
                    self.rail.selected_index = value
                else:
                    setattr(self, name, value)
            except Exception:
                self._write_runtime_error(
                    f"恢复交互状态失败：{name}",
                    traceback.format_exc(),
                )

    def _wrap_event_handler(
        self,
        handler,
        context: str,
        message: str | None = None,
    ):
        if getattr(handler, "_entp_exception_boundary", False):
            return handler
        if inspect.iscoroutinefunction(handler):
            async def guarded_async(*args, **kwargs):
                snapshot = self._interaction_state_snapshot()
                try:
                    return await handler(*args, **kwargs)
                except Exception as error:
                    details = traceback.format_exc()
                    self._restore_interaction_state(snapshot)
                    self._report_interaction_error(context, error, message, details)
                    return None

            guarded_async._entp_exception_boundary = True
            guarded_async.__name__ = getattr(handler, "__name__", "guarded_async_event")
            return guarded_async

        def guarded_sync(*args, **kwargs):
            snapshot = self._interaction_state_snapshot()
            try:
                return handler(*args, **kwargs)
            except Exception as error:
                details = traceback.format_exc()
                self._restore_interaction_state(snapshot)
                self._report_interaction_error(context, error, message, details)
                return None

        guarded_sync._entp_exception_boundary = True
        guarded_sync.__name__ = getattr(handler, "__name__", "guarded_event")
        return guarded_sync

    def _protect_control_tree(self, root: ft.Control | None) -> None:
        if root is None:
            return
        pending: list[ft.Control] = [root]
        visited: set[int] = set()
        while pending:
            control = pending.pop()
            identity = id(control)
            if identity in visited:
                continue
            visited.add(identity)
            values = getattr(control, "_values", {})
            for event_name, handler in list(values.items()):
                if event_name.startswith("on_") and callable(handler):
                    setattr(
                        control,
                        event_name,
                        self._wrap_event_handler(
                            handler,
                            self._control_label(control, event_name),
                        ),
                    )
            candidates = list(values.values())
            for name, value in getattr(control, "__dict__", {}).items():
                if name not in {"_values", "_dirty", "_internals", "data"}:
                    candidates.append(value)
            for value in candidates:
                if isinstance(value, ft.Control):
                    pending.append(value)
                elif isinstance(value, (list, tuple)):
                    pending.extend(item for item in value if isinstance(item, ft.Control))

    def _protected_page_update(self, *controls: ft.Control) -> None:
        roots = list(controls)
        if not roots:
            roots.extend(getattr(self.page, "controls", []))
            roots.extend(getattr(self.page, "overlay", []))
        for control in roots:
            self._protect_control_tree(control)
        self._original_page_update(*controls)

    def interaction_boundary_audit(self) -> tuple[int, list[str]]:
        total = 0
        unprotected: list[str] = []
        lifecycle_handlers = (
            ("Page.on_close", getattr(self.page, "on_close", None)),
            ("Page.on_disconnect", getattr(self.page, "on_disconnect", None)),
            ("Window.on_event", getattr(getattr(self.page, "window", None), "on_event", None)),
        )
        for label, handler in lifecycle_handlers:
            if callable(handler):
                total += 1
                if not getattr(handler, "_entp_exception_boundary", False):
                    unprotected.append(label)
        pending = [
            *getattr(self.page, "controls", []),
            *getattr(self.page, "overlay", []),
        ]
        visited: set[int] = set()
        while pending:
            control = pending.pop()
            identity = id(control)
            if identity in visited:
                continue
            visited.add(identity)
            values = getattr(control, "_values", {})
            for event_name, handler in values.items():
                if event_name.startswith("on_") and callable(handler):
                    total += 1
                    if not getattr(handler, "_entp_exception_boundary", False):
                        unprotected.append(self._control_label(control, event_name))
            candidates = list(values.values())
            for name, value in getattr(control, "__dict__", {}).items():
                if name not in {"_values", "_dirty", "_internals", "data"}:
                    candidates.append(value)
            for value in candidates:
                if isinstance(value, ft.Control):
                    pending.append(value)
                elif isinstance(value, (list, tuple)):
                    pending.extend(item for item in value if isinstance(item, ft.Control))
        return total, unprotected

    def _guard_ui_action(self, context: str, action, message: str):
        """Keep a single failed interaction from escaping into the Flet session."""
        return self._wrap_event_handler(
            action,
            context,
            f"{message}。当前页面和数据不受影响，可以继续使用。",
        )

    def _close_database(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.db.close()
        except Exception:
            self._write_runtime_error("关闭数据库连接失败", traceback.format_exc())

    def _reopen_workspace(self, database_path: Path, markdown_root: Path) -> None:
        self.db = Database(database_path)
        self.markdown = MarkdownStore(markdown_root)
        self._closed = False

    def _reset_workspace_view_state(self) -> None:
        self.current_mid = self.db.current_mainline_id()
        self.today = date.today()
        self._observed_local_day = self.today
        self.selected_day = self.today
        self.calendar_month = self.today.replace(day=1)
        self.calendar_selected_day = self.today
        self.selected_task_id = None
        self.selected_thought_id = None
        self.selected_mainline_id = None
        self.inspiration_capture_open = False

    def _handle_page_closed(self, _=None) -> None:
        self._close_database()

    async def _handle_window_event(self, event) -> None:
        if event.type == ft.WindowEventType.CLOSE:
            self._close_database()
            await self.page.window.destroy()

    def _build_rail(self) -> ft.NavigationRail:
        brand = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(ft.Icons.BOLT_ROUNDED, size=24, color=ft.Colors.WHITE),
                        width=42,
                        height=42,
                        alignment=ft.Alignment.CENTER,
                        bgcolor=BLUE,
                        border_radius=14,
                    ),
                    ft.Column(
                        [
                            ft.Text("ENTP 自强手册", size=15, weight=ft.FontWeight.W_700, color=INK),
                            ft.Text("好奇心动力回流系统", size=12, color=MUTED),
                        ],
                        spacing=1,
                    ),
                ],
                spacing=12,
            ),
            padding=ft.Padding.only(left=18, right=12, top=24, bottom=28),
        )
        return ft.NavigationRail(
            extended=True,
            min_width=82,
            min_extended_width=236,
            selected_index=0,
            bgcolor=SIDEBAR,
            indicator_color=BLUE_SOFT,
            indicator_shape=rounded(14),
            use_indicator=True,
            label_type=ft.NavigationRailLabelType.NONE,
            selected_label_text_style=ft.TextStyle(size=14, weight=ft.FontWeight.W_700, color=BLUE_DARK),
            unselected_label_text_style=ft.TextStyle(size=14, weight=ft.FontWeight.W_500, color="#515762"),
            leading=brand,
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.Icons.FLAG_OUTLINED,
                    selected_icon=ft.Icons.FLAG_ROUNDED,
                    label="当前主线",
                    padding=12,
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.INVENTORY_2_OUTLINED,
                    selected_icon=ft.Icons.INVENTORY_2_ROUNDED,
                    label="我的主线任务保管箱",
                    padding=12,
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.LIGHTBULB_OUTLINE_ROUNDED,
                    selected_icon=ft.Icons.LIGHTBULB_ROUNDED,
                    label="候审区",
                    padding=12,
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.CHECKLIST_ROUNDED,
                    selected_icon=ft.Icons.FACT_CHECK_ROUNDED,
                    label="今日清单",
                    padding=12,
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.CALENDAR_MONTH_OUTLINED,
                    selected_icon=ft.Icons.CALENDAR_MONTH_ROUNDED,
                    label="完成日历",
                    padding=12,
                ),
            ],
            trailing=ft.Container(
                content=ft.Column(
                    [
                        ft.Divider(height=1, color=LINE),
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=19, color=MUTED),
                                ft.Text("每个小块都有 Markdown", size=12, color=MUTED),
                            ],
                            spacing=9,
                        ),
                        ft.Row(
                            [
                                ft.Container(width=8, height=8, bgcolor=GREEN, border_radius=99),
                                ft.Text("本地 SQLite 已连接", size=12, color=MUTED),
                            ],
                            spacing=9,
                        ),
                    ],
                    spacing=14,
                ),
                padding=ft.Padding.only(left=22, right=16, bottom=24),
            ),
            pin_trailing_to_bottom=True,
            on_change=lambda e: self.show_view(int(e.control.selected_index)),
        )

    def show_view(self, index: int) -> None:
        self.active_index = index
        self.rail.selected_index = index
        if index == self.NAV_CURRENT:
            self.refresh_current_sections(update=False)
            view = self._current_view()
        elif index == self.NAV_VAULT:
            self.refresh_vault(update=False)
            view = self._vault_view()
        elif index == self.NAV_IDEAS:
            if self.selected_thought_id is not None:
                view = self._idea_review_view(self.selected_thought_id)
            else:
                self.idea_board_control = self._ideas_board_view()
                view = self.idea_board_control
        elif index == self.NAV_TODAY:
            self._refresh_local_day()
            view = self._today_view()
        elif index == self.NAV_CALENDAR:
            self._refresh_local_day()
            view = self._completion_calendar_view()
        else:
            view = self._phase_placeholder("暂未开放", "这个页面还没有迁移。", ft.Icons.CONSTRUCTION_ROUNDED)
        self.content_switcher.content = view
        self.page.update()

    def _page_shell(self, content: ft.Control) -> ft.Container:
        return ft.Container(
            content=content,
            padding=ft.Padding.symmetric(horizontal=26, vertical=26),
            expand=True,
        )

    def _current_view(self) -> ft.Container:
        left = ft.Container(
            content=ft.Column(
                [self.quick_task_box, self.focus_holder, self.task_holder],
                spacing=18,
                scroll=ft.ScrollMode.AUTO,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            col={
                ft.ResponsiveRowBreakpoint.XS: 12,
                ft.ResponsiveRowBreakpoint.SM: 12,
                ft.ResponsiveRowBreakpoint.MD: 12,
                ft.ResponsiveRowBreakpoint.LG: 7,
                ft.ResponsiveRowBreakpoint.XL: 7,
                ft.ResponsiveRowBreakpoint.XXL: 7,
            },
            padding=ft.Padding.only(right=8),
        )
        right = ft.Container(
            content=self.detail_holder,
            col={
                ft.ResponsiveRowBreakpoint.XS: 12,
                ft.ResponsiveRowBreakpoint.SM: 12,
                ft.ResponsiveRowBreakpoint.MD: 12,
                ft.ResponsiveRowBreakpoint.LG: 5,
                ft.ResponsiveRowBreakpoint.XL: 5,
                ft.ResponsiveRowBreakpoint.XXL: 5,
            },
            padding=ft.Padding.only(left=8),
        )
        task_calendar_layout: ft.Control = ft.ResponsiveRow(
            [left, right], spacing=14, run_spacing=18
        )
        return self._page_shell(
            ft.Column(
                [
                    self.current_header,
                    task_calendar_layout,
                ],
                spacing=26,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    def refresh_current_sections(self, *, update: bool = True) -> None:
        self.current_mid = self.db.current_mainline_id()
        mainline = next(m for m in self.db.list_mainlines() if int(m["id"]) == self.current_mid)
        tasks = self.db.list_tasks(self.current_mid)
        focus = self.db.get_focus_task(self.current_mid)
        rhythm = str(mainline["review_mode"] or "按需复盘")
        until = str(mainline["focus_until"] or "")
        rhythm_text = rhythm if not until else f"{rhythm} · 至 {until}"
        self.current_header.controls = [
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text("当前主线", size=13, weight=ft.FontWeight.W_700, color=BLUE),
                                    pill(rhythm_text, color=MUTED, bgcolor="#F0F1F4", icon=ft.Icons.TUNE_ROUNDED),
                                ],
                                spacing=10,
                            ),
                            ft.Text(str(mainline["name"]), size=28, weight=ft.FontWeight.W_700, color=INK),
                            ft.Text(
                                str(mainline["vision"] or ""),
                                size=15,
                                color=MUTED,
                            ),
                        ],
                        spacing=8,
                        expand=True,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.END,
            ),
        ]
        self.focus_holder.content = self._focus_card(focus)
        self.focus_holder.visible = self.selected_task_id is None
        self.task_holder.controls = self._task_section(tasks)
        self.calendar_holder.content = self._calendar_card(self.today.year, self.today.month)
        selected = next(
            (task for task in tasks if int(task["id"]) == self.selected_task_id),
            None,
        )
        if self.selected_task_id is not None and selected is None:
            self.selected_task_id = None
        self.detail_holder.content = (
            self._task_detail_panel(selected)
            if selected is not None
            else self.calendar_holder
        )
        if update:
            self.page.update()

    def _focus_card(self, focus) -> ft.Card:
        if not focus:
            body = ft.Column(
                [
                    section_title("现在只推进一件事"),
                    ft.Text("还没有焦点任务。直接在上方输入任务，或从下方任务中选择一项。", size=15, color=MUTED),
                    ft.OutlinedButton(
                            "暂存新灵感",
                            icon=ft.Icons.LIGHTBULB_OUTLINE_ROUNDED,
                            on_click=self.open_inline_inspiration,
                        style=ft.ButtonStyle(
                            shape=rounded(13),
                            padding=18,
                            color=AMBER,
                            side=ft.BorderSide(1, "#F0D8A1"),
                        ),
                    ),
                    *([self._inline_inspiration_capture()] if self.inspiration_capture_open else []),
                ],
                spacing=14,
            )
        else:
            task_id = int(focus["id"])
            next_action = str(focus["next_action"] or "把它改写成一个 15 分钟内能开始的小动作")
            body = ft.Column(
                [
                    ft.Row(
                        [
                            pill("正在执行", color=GREEN, bgcolor=GREEN_SOFT, icon=ft.Icons.PLAY_ARROW_ROUNDED),
                            ft.Text("不是想通，而是在现实里留下变化", size=13, color=MUTED),
                            ft.IconButton(
                                ft.Icons.DESCRIPTION_OUTLINED,
                                tooltip="打开任务 Markdown",
                                icon_color=MUTED,
                                on_click=lambda _: self.open_markdown("task", task_id),
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Text(str(focus["title"]), size=21, weight=ft.FontWeight.W_700, color=INK),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.NEAR_ME_ROUNDED, size=20, color=BLUE),
                                ft.Column(
                                    [
                                        ft.Text("下一步最小行动", size=12, color=MUTED),
                                        ft.Text(next_action, size=16, weight=ft.FontWeight.W_600, color=INK),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.IconButton(
                                    ft.Icons.EDIT_OUTLINED,
                                    tooltip="修改下一步",
                                    icon_color=MUTED,
                                    on_click=lambda _: self.select_task(task_id),
                                ),
                            ]
                        ),
                        padding=16,
                        bgcolor=BLUE_SOFT,
                        border_radius=14,
                    ),
                    ft.Row(
                        [
                            ft.FilledButton(
                                "记录一次执行",
                                icon=ft.Icons.ADD_TASK_ROUNDED,
                                on_click=lambda _: self.open_execution_dialog(task_id),
                                style=ft.ButtonStyle(shape=rounded(13), padding=18, bgcolor=BLUE, color=ft.Colors.WHITE),
                            ),
                            ft.OutlinedButton(
                                "没动力了",
                                icon=ft.Icons.AUTO_AWESOME_ROUNDED,
                                on_click=lambda _: self.open_stuck_dialog(task_id),
                                style=ft.ButtonStyle(shape=rounded(13), padding=18, color=INK, side=ft.BorderSide(1, LINE)),
                            ),
                            ft.OutlinedButton(
                                "暂存新灵感",
                                icon=ft.Icons.LIGHTBULB_OUTLINE_ROUNDED,
                                on_click=self.open_inline_inspiration,
                                style=ft.ButtonStyle(
                                    shape=rounded(13),
                                    padding=18,
                                    color=AMBER,
                                    side=ft.BorderSide(1, "#F0D8A1"),
                                ),
                            ),
                        ],
                        spacing=12,
                        wrap=True,
                    ),
                    *([self._inline_inspiration_capture()] if self.inspiration_capture_open else []),
                ],
                spacing=16,
            )
        return ft.Card(
            content=ft.Container(body, padding=24),
            elevation=0,
            bgcolor=SURFACE,
            shape=rounded(20),
            variant=ft.CardVariant.OUTLINED,
        )

    def _task_section(self, tasks) -> list[ft.Control]:
        active = [t for t in tasks if str(t["status"]) != "完成"]
        completed = [t for t in tasks if str(t["status"]) == "完成"]
        rows: list[ft.Control] = [
            ft.Row(
                [
                    section_title("这条主线的任务", f"{len(active)} 个待推进"),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        ]
        rows.extend(self._task_row(t, completed=False) for t in active)
        if completed:
            rows.append(
                ft.Container(
                    section_title("已完成", f"{len(completed)} 个现实结果"),
                    padding=ft.Padding.only(top=20, bottom=6),
                )
            )
            rows.extend(self._task_row(t, completed=True) for t in completed)
        return rows

    def _task_row(self, task, *, completed: bool) -> ft.Control:
        task_id = int(task["id"])
        focused = bool(task["is_focus"])
        selected = task_id == self.selected_task_id
        title = str(task["title"])
        next_action = str(task["next_action"] or "")
        status_hint = "现实完成已记入日历" if completed else (next_action or " ")
        trailing = (
            pill("当前", color=BLUE, bgcolor=BLUE_SOFT)
            if focused and not completed
            else ft.IconButton(
                ft.Icons.FLAG_OUTLINED,
                tooltip="设为当前任务",
                icon_color=MUTED,
                on_click=lambda _, tid=task_id: self.set_focus_task(tid),
                visible=not completed,
            )
        )
        tile = ft.Container(
            content=ft.ListTile(
                leading=ft.Checkbox(
                    value=completed,
                    active_color=GREEN,
                    on_change=lambda e, tid=task_id: self.toggle_task(
                        tid, bool(e.control.value)
                    ),
                ),
                title=ft.Text(
                    title,
                    size=16,
                    weight=ft.FontWeight.W_600,
                    color="#A5A9B2" if completed else INK,
                ),
                subtitle=ft.Text(
                    status_hint,
                    size=13,
                    color="#B3B6BD" if completed else MUTED,
                ),
                trailing=ft.Row(
                    [
                        ft.IconButton(
                            ft.Icons.DESCRIPTION_OUTLINED,
                            tooltip="打开任务 Markdown",
                            icon_color=MUTED,
                            on_click=lambda _, tid=task_id: self.open_markdown("task", tid),
                        ),
                        trailing,
                    ],
                    spacing=2,
                    tight=True,
                ),
                content_padding=ft.Padding.symmetric(horizontal=12, vertical=11),
                min_height=92,
                on_click=lambda _, tid=task_id: self.select_task(tid),
            ),
            bgcolor="#F1F2F4" if selected else ("#FAFAFB" if completed else SURFACE),
            border_radius=14 if selected else 0,
            animate=120,
        )
        return ft.Column(
            [
                tile,
                ft.Divider(
                    height=1,
                    color=LINE,
                    leading_indent=56,
                    trailing_indent=8,
                ),
            ],
            spacing=0,
        )

    def _task_detail_panel(self, task) -> ft.Card:
        task_id = int(task["id"])
        completed = str(task["status"]) == "完成"
        focused = bool(task["is_focus"])
        title_field = ft.TextField(
            value=str(task["title"]),
            border=ft.InputBorder.NONE,
            text_size=23,
            text_style=ft.TextStyle(weight=ft.FontWeight.W_700, color=INK),
            content_padding=0,
        )
        description_field = ft.TextField(
            value=str(task["description"] or ""),
            hint_text="输入内容，记录背景、思路或判断……",
            hint_style=ft.TextStyle(size=15, color="#B3B6BD"),
            border=ft.InputBorder.NONE,
            multiline=True,
            min_lines=8,
            max_lines=18,
            text_size=15,
            content_padding=0,
        )
        next_action_field = ft.TextField(
            value=str(task["next_action"] or ""),
            label="下一步最小行动",
            label_style=ft.TextStyle(size=13, color=MUTED),
            hint_text="写下可以马上开始的一步",
            text_size=14,
            border_radius=12,
            border_color=LINE,
            focused_border_color=BLUE,
        )

        def save_fields(_) -> None:
            title = title_field.value.strip() or str(task["title"])
            self.db.update_task(
                task_id,
                title=title,
                description=description_field.value,
                next_action=next_action_field.value,
            )
            self._sync_markdown()

        title_field.on_blur = save_fields
        description_field.on_blur = save_fields
        next_action_field.on_blur = save_fields

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Checkbox(
                                    value=completed,
                                    active_color=GREEN,
                                    on_change=lambda e, tid=task_id: self.toggle_task(
                                        tid, bool(e.control.value)
                                    ),
                                ),
                                pill(
                                    "已完成" if completed else "待执行",
                                    color=GREEN if completed else BLUE,
                                    bgcolor=GREEN_SOFT if completed else BLUE_SOFT,
                                ),
                                ft.Container(expand=True),
                                ft.IconButton(
                                    ft.Icons.FLAG_ROUNDED if focused else ft.Icons.FLAG_OUTLINED,
                                    tooltip="设为当前任务",
                                    icon_color=BLUE if focused else MUTED,
                                    on_click=lambda _: self.set_focus_task(task_id),
                                    disabled=completed,
                                ),
                                ft.IconButton(
                                    ft.Icons.CLOSE_ROUNDED,
                                    tooltip="关闭任务详情",
                                    icon_color=MUTED,
                                    on_click=lambda _: self.close_task_detail(),
                                ),
                            ],
                            spacing=6,
                        ),
                        title_field,
                        description_field,
                        next_action_field,
                        ft.Divider(height=1, color=LINE),
                        ft.Row(
                            [
                                ft.TextButton(
                                    "打开 Markdown",
                                    icon=ft.Icons.DESCRIPTION_OUTLINED,
                                    on_click=lambda _: self.open_markdown("task", task_id),
                                ),
                                ft.Text("离开输入框时自动保存", size=12, color=MUTED),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=14,
                ),
                padding=ft.Padding.symmetric(horizontal=24, vertical=20),
                height=610,
            ),
            elevation=0,
            bgcolor=SURFACE,
            shape=rounded(20),
            variant=ft.CardVariant.OUTLINED,
        )

    def _calendar_card(self, year: int, month: int) -> ft.Card:
        completion = self.db.completion_days(year, month, self.current_mid)
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
        day_headers = [ft.Container(ft.Text(x, size=12, color=MUTED, text_align=ft.TextAlign.CENTER), col=1) for x in "一二三四五六日"]
        day_cells: list[ft.Control] = []
        today_iso = self.today.isoformat()
        for week in weeks:
            for day_num in week:
                if day_num == 0:
                    day_cells.append(ft.Container(height=43, col=1))
                    continue
                day_iso = f"{year:04d}-{month:02d}-{day_num:02d}"
                count = completion.get(day_iso, 0)
                is_today = day_iso == today_iso
                cell = ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                str(day_num),
                                size=13,
                                weight=ft.FontWeight.W_700 if is_today else ft.FontWeight.W_500,
                                color=ft.Colors.WHITE if is_today else INK,
                            ),
                            ft.Container(
                                width=5,
                                height=5,
                                bgcolor=ft.Colors.WHITE if is_today and count else (GREEN if count else "#00000000"),
                                border_radius=99,
                            ),
                        ],
                        spacing=1,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    height=43,
                    bgcolor=BLUE if is_today else (GREEN_SOFT if count else "#00000000"),
                    border_radius=12,
                    col=1,
                    tooltip=f"{day_iso} · 完成 {count} 项" if count else day_iso,
                    on_click=self._guard_ui_action(
                        "打开执行区完成日历日期失败",
                        lambda _, picked=date(year, month, day_num): (
                            self.open_completion_calendar(picked)
                            if picked <= date.today()
                            else None
                        ),
                        "无法打开这个日期",
                    ),
                )
                day_cells.append(cell)
        recent = self.db.completed_entries_on(today_iso, self.current_mid)
        evidence: list[ft.Control] = []
        for item in recent[:3]:
            evidence.append(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=17, color=GREEN),
                        ft.Text(str(item["title"]), size=13, color=INK, expand=True, max_lines=1),
                    ],
                    spacing=8,
                )
            )
        if not evidence:
            evidence = [ft.Text("今天完成的任务会沉淀在这里。", size=13, color=MUTED)]
        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text("完成日历", size=20, weight=ft.FontWeight.W_700, color=INK),
                                        ft.Text("记录现实发生过什么", size=13, color=MUTED),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                pill(f"{year} / {month:02d}", color=INK, bgcolor="#F1F2F5"),
                            ]
                        ),
                        ft.ResponsiveRow(day_headers, columns=7, spacing=4),
                        ft.ResponsiveRow(day_cells, columns=7, spacing=4, run_spacing=4),
                        ft.Divider(height=1, color=LINE),
                        ft.Text("今天留下的现实证据", size=14, weight=ft.FontWeight.W_700, color=INK),
                        ft.Column(evidence, spacing=10),
                        ft.Text(
                            "“现实证据”不是额外填写的表格，而是任务完成和执行记录自动留下的结果。",
                            size=12,
                            color=MUTED,
                        ),
                    ],
                    spacing=16,
                ),
                padding=22,
            ),
            elevation=0,
            bgcolor=SURFACE,
            shape=rounded(20),
            variant=ft.CardVariant.OUTLINED,
        )

    @staticmethod
    def _idea_stage_spec(status: str) -> tuple[str, str, object]:
        specs = {
            "未审视": ("未审视", "#6F7682", ft.Icons.RADIO_BUTTON_UNCHECKED_ROUNDED),
            "待孵化": ("待孵化", AMBER, ft.Icons.LIGHTBULB_OUTLINE_ROUNDED),
            "正在尝试": ("正在尝试", GREEN, ft.Icons.SCIENCE_OUTLINED),
            "已归档": ("已归档", "#8B9099", ft.Icons.ARCHIVE_OUTLINED),
        }
        return specs.get(status, specs["未审视"])

    def _idea_card(self, thought) -> ft.Control:
        thought_id = int(thought["id"])
        status = str(thought["status"] or "未审视")
        raw = str(thought["raw_content"] or "").strip()
        tags = [tag.strip() for tag in str(thought["tags"] or "").replace("，", ",").split(",") if tag.strip()]
        created = str(thought["created_at"] or "")[:10]
        body: list[ft.Control] = [
            ft.Text(
                str(thought["title"]),
                size=16,
                weight=ft.FontWeight.W_700,
                color=INK,
                max_lines=2,
            )
        ]
        if raw:
            body.append(ft.Text(raw, size=13, color=MUTED, max_lines=2))
        footer: list[ft.Control] = []
        if tags:
            footer.append(ft.Text("  ".join(f"#{tag}" for tag in tags[:2]), size=12, color=BLUE, max_lines=1))
        footer.extend(
            [
                ft.Container(expand=True),
                ft.Text(created[5:] if len(created) >= 10 else created, size=12, color="#9A9EA7"),
                ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=18, color="#A1A5AE"),
            ]
        )
        body.append(ft.Row(footer, spacing=6))
        return ft.Container(
            content=ft.Column(body, spacing=10),
            padding=15,
            bgcolor=SURFACE,
            border=ft.Border.all(1, "#F1D39B" if status == "待孵化" else LINE),
            border_radius=14,
            shadow=ft.BoxShadow(blur_radius=9, color="#0A15200A", offset=ft.Offset(0, 2)),
            ink=True,
            on_click=lambda _, tid=thought_id: self.open_thought_review(tid),
            tooltip="展开审视这条灵感",
        )

    def _ideas_board_view(self) -> ft.Container:
        thoughts = self.db.list_thoughts()
        stages = ("未审视", "待孵化", "正在尝试", "已归档")
        stage_height = max(360, min(620, float(self.page.height or 760) - 250))
        stage_columns: list[ft.Control] = []
        for status in stages:
            label, color, icon = self._idea_stage_spec(status)
            items = [t for t in thoughts if str(t["status"]) == status]
            cards: list[ft.Control] = [self._idea_card(t) for t in items]
            if not cards:
                cards.append(
                    ft.Container(
                        ft.Text("这里暂时是空的", size=13, color="#A3A7AF"),
                        padding=18,
                        alignment=ft.Alignment.CENTER,
                        border=ft.Border.all(1, LINE),
                        border_radius=14,
                    )
                )
            stage_columns.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(icon, size=18, color=color),
                                    ft.Text(label, size=16, weight=ft.FontWeight.W_700, color=INK),
                                    ft.Text(str(len(items)), size=13, color=MUTED),
                                ],
                                spacing=7,
                            ),
                            ft.Column(cards, spacing=10, scroll=ft.ScrollMode.AUTO, expand=True),
                        ],
                        spacing=12,
                        expand=True,
                    ),
                    height=stage_height,
                    col={
                        ft.ResponsiveRowBreakpoint.XS: 12,
                        ft.ResponsiveRowBreakpoint.SM: 12,
                        ft.ResponsiveRowBreakpoint.MD: 6,
                        ft.ResponsiveRowBreakpoint.LG: 3,
                        ft.ResponsiveRowBreakpoint.XL: 3,
                        ft.ResponsiveRowBreakpoint.XXL: 3,
                    },
                    padding=14,
                    bgcolor="#F8F9FB",
                    border=ft.Border.all(1, LINE),
                    border_radius=17,
                )
            )

        quick_box = ft.Container(
            content=ft.Row(
                [
                    ft.Container(self.quick_idea_input, expand=True),
                    ft.FilledButton(
                        "放入候审区",
                        icon=ft.Icons.MOVE_TO_INBOX_ROUNDED,
                        on_click=lambda _: self.quick_add_idea(None),
                        style=ft.ButtonStyle(
                            bgcolor=AMBER,
                            color=ft.Colors.WHITE,
                            shape=rounded(12),
                            padding=ft.Padding.symmetric(horizontal=18, vertical=16),
                        ),
                    ),
                ],
                spacing=8,
            ),
            padding=ft.Padding.only(left=5, right=8),
            bgcolor=SURFACE,
            border=ft.Border.all(1, LINE),
            border_radius=16,
        )
        return self._page_shell(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text("候审区", size=29, weight=ft.FontWeight.W_700, color=INK),
                                    ft.Text("审视灵感，不急着决定它属于哪里", size=15, color=MUTED),
                                ],
                                spacing=5,
                                expand=True,
                            ),
                            ft.OutlinedButton(
                                "没动力了？随便翻一翻",
                                icon=ft.Icons.AUTO_AWESOME_ROUNDED,
                                on_click=lambda _: self.open_first_unreviewed(),
                                style=ft.ButtonStyle(
                                    color=BLUE,
                                    side=ft.BorderSide(1, "#C9D8FF"),
                                    shape=rounded(99),
                                    padding=ft.Padding.symmetric(horizontal=17, vertical=13),
                                ),
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    quick_box,
                    ft.ResponsiveRow(
                        stage_columns,
                        spacing=14,
                        run_spacing=14,
                    ),
                ],
                spacing=20,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    def quick_add_idea(self, event) -> None:
        title = str(self.quick_idea_input.value or "").strip()
        if not title:
            self.quick_idea_input.error_text = "先写下一句话灵感"
            self.quick_idea_input.update()
            return
        self.db.create_thought(title, mainline_id=None)
        self._sync_markdown()
        self.quick_idea_input.value = ""
        self.quick_idea_input.error_text = None
        self.selected_thought_id = None
        self.show_view(self.NAV_IDEAS)

    def open_first_unreviewed(self) -> None:
        thoughts = self.db.list_thoughts(statuses=("未审视",))
        if not thoughts:
            thoughts = self.db.list_thoughts(statuses=("待孵化",))
        if thoughts:
            self.open_thought_review(int(thoughts[0]["id"]))

    def open_thought_review(self, thought_id: int) -> None:
        if not self.db.get_thought(thought_id):
            return
        self.selected_thought_id = thought_id
        self.content_switcher.content = self._idea_review_view(thought_id)
        self.page.update()

    def close_thought_review(self) -> None:
        self.selected_thought_id = None
        self.show_view(self.NAV_IDEAS)

    def _review_dropdown(
        self,
        *,
        label: str,
        value: str,
        values: list[tuple[str, str]],
        on_select,
    ) -> ft.Dropdown:
        return ft.Dropdown(
            label=label,
            value=value,
            options=[ft.DropdownOption(key=key, text=text) for key, text in values],
            text_size=14,
            border_radius=12,
            border_color=LINE,
            focused_border_color=BLUE,
            content_padding=ft.Padding.symmetric(horizontal=13, vertical=10),
            dense=True,
            on_select=on_select,
        )

    def _idea_queue_item(self, thought, selected_id: int) -> ft.Control:
        thought_id = int(thought["id"])
        selected = thought_id == selected_id
        status = str(thought["status"])
        _, color, _ = self._idea_stage_spec(status)
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        str(thought["title"]),
                        size=14,
                        weight=ft.FontWeight.W_700 if selected else ft.FontWeight.W_600,
                        color=INK,
                        max_lines=2,
                    ),
                    ft.Row(
                        [
                            ft.Container(width=6, height=6, bgcolor=color, border_radius=99),
                            ft.Text(status, size=11, color=MUTED),
                            ft.Container(expand=True),
                            ft.Text(str(thought["created_at"] or "")[:10], size=11, color="#A0A4AC"),
                        ],
                        spacing=6,
                    ),
                ],
                spacing=7,
            ),
            padding=12,
            bgcolor=BLUE_SOFT if selected else SURFACE,
            border=ft.Border.all(1, "#BFD0FF" if selected else LINE),
            border_radius=12,
            ink=True,
            on_click=lambda _, tid=thought_id: self.open_thought_review(tid),
        )

    def _idea_review_view(self, thought_id: int) -> ft.Container:
        thought = self.db.get_thought(thought_id)
        if not thought:
            self.selected_thought_id = None
            return self._ideas_board_view()
        panel_height = max(560, min(760, float(self.page.height or 760) - 105))

        title_field = ft.TextField(
            value=str(thought["title"]),
            border=ft.InputBorder.NONE,
            text_size=25,
            text_style=ft.TextStyle(weight=ft.FontWeight.W_700, color=INK),
            content_padding=0,
        )
        raw_field = ft.TextField(
            value=str(thought["raw_content"] or ""),
            border=ft.InputBorder.NONE,
            multiline=True,
            min_lines=18,
            max_lines=30,
            text_size=16,
            content_padding=ft.Padding.only(top=8),
            expand=True,
        )

        tags = [
            tag.strip()
            for tag in str(thought["tags"] or "").replace("，", ",").split(",")
            if tag.strip()
        ]
        tag_input = ft.TextField(
            hint_text="＋ 添加标签",
            hint_style=ft.TextStyle(size=13, color=MUTED),
            border=ft.InputBorder.NONE,
            text_size=13,
            width=130,
            height=38,
            content_padding=ft.Padding.symmetric(horizontal=7, vertical=8),
        )
        tag_holder = ft.Row(spacing=6, wrap=True)

        def save_all(_=None) -> None:
            self.db.update_thought(
                thought_id,
                title=title_field.value.strip() or str(thought["title"]),
                raw_content=raw_field.value,
                conclusion=str(thought["conclusion"] or ""),
                evidence=str(thought["evidence"] or ""),
                next_step=str(thought["next_step"] or ""),
                status=str(status_dropdown.value or "未审视"),
                progress=int(thought["progress"] or 0),
                mainline_id=thought["mainline_id"],
                category=str(thought["category"] or "未分类"),
                interest_level=str(thought["interest_level"] or "有点好奇"),
                tags=",".join(tags),
            )
            self._sync_markdown()

        def remove_tag(tag: str) -> None:
            if tag in tags:
                tags.remove(tag)
            render_tags()
            save_all()
            self.page.update()

        def render_tags() -> None:
            tag_holder.controls = [
                ft.Chip(
                    label=ft.Text(tag, size=12, color=BLUE_DARK),
                    bgcolor=BLUE_SOFT,
                    shape=rounded(99),
                    delete_icon=ft.Icon(ft.Icons.CLOSE_ROUNDED, size=14),
                    on_delete=lambda _, value=tag: remove_tag(value),
                    padding=2,
                )
                for tag in tags
            ] + [tag_input]

        def add_tag(_=None) -> None:
            values = [
                value.strip()
                for value in str(tag_input.value or "").replace("，", ",").split(",")
                if value.strip()
            ]
            for value in values:
                if value not in tags:
                    tags.append(value)
            tag_input.value = ""
            render_tags()
            save_all()
            self.page.update()

        def change_status(_=None) -> None:
            save_all()
            self.content_switcher.content = self._idea_review_view(thought_id)
            self.page.update()

        status_values = [(s, s) for s in ("未审视", "待孵化", "正在尝试", "已归档")]
        status_dropdown = self._review_dropdown(
            label="状态",
            value=str(thought["status"]),
            values=status_values,
            on_select=change_status,
        )
        status_dropdown.width = 150
        tag_input.on_submit = add_tag
        render_tags()
        for field in (title_field, raw_field):
            field.on_blur = save_all

        all_thoughts = self.db.list_thoughts()
        queue = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("全部灵感", size=16, weight=ft.FontWeight.W_700, color=INK),
                            ft.Text(str(len(all_thoughts)), size=12, color=MUTED),
                        ],
                        spacing=7,
                    ),
                    ft.Column(
                        [self._idea_queue_item(t, thought_id) for t in all_thoughts],
                        spacing=8,
                        scroll=ft.ScrollMode.AUTO,
                        expand=True,
                    ),
                ],
                spacing=12,
                expand=True,
            ),
            padding=14,
            bgcolor="#F8F9FB",
            border=ft.Border.all(1, LINE),
            border_radius=17,
            height=panel_height,
            col={ft.ResponsiveRowBreakpoint.XS: 12, ft.ResponsiveRowBreakpoint.MD: 4, ft.ResponsiveRowBreakpoint.LG: 3},
        )

        editor = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(title_field, expand=True),
                            status_dropdown,
                        ],
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    ft.Text(f"记录于 {str(thought['created_at'])[:16]}", size=13, color=MUTED),
                    tag_holder,
                    ft.Divider(height=1, color=LINE),
                    raw_field,
                    ft.Row(
                        [
                            ft.TextButton(
                                "打开 Markdown",
                                icon=ft.Icons.DESCRIPTION_OUTLINED,
                                on_click=lambda _: self.open_markdown("thought", thought_id),
                            ),
                            ft.Text("离开输入框时自动保存", size=12, color=MUTED),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ],
                spacing=10,
            ),
            padding=22,
            bgcolor=SURFACE,
            border=ft.Border.all(1, LINE),
            border_radius=17,
            height=panel_height,
            col={ft.ResponsiveRowBreakpoint.XS: 12, ft.ResponsiveRowBreakpoint.MD: 8, ft.ResponsiveRowBreakpoint.LG: 9},
        )
        workspace_controls: list[ft.Control] = [queue, editor]
        if float(self.page.width or 1400) < 1100:
            editor.col = 12
            workspace_controls = [editor]

        return self._page_shell(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.TextButton(
                                "返回候审看板",
                                icon=ft.Icons.ARROW_BACK_ROUNDED,
                                on_click=lambda _: self.close_thought_review(),
                            ),
                            ft.Container(expand=True),
                            ft.Text("候审区 / 审视灵感", size=13, color=MUTED),
                        ]
                    ),
                    ft.ResponsiveRow(
                        workspace_controls,
                        spacing=14,
                        run_spacing=14,
                    ),
                ],
                spacing=14,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    def _vault_view(self) -> ft.Container:
        return self._page_shell(
            ft.Column(
                [
                    ft.Column(
                        [
                            ft.Column(
                                [
                                    ft.Text("我的主线任务保管箱", size=28, weight=ft.FontWeight.W_700, color=INK),
                                    ft.Text("其他主线留在这里，不与正在执行的事情争夺注意力。", size=16, color=MUTED),
                                ],
                                spacing=8,
                            ),
                            ft.Row(
                                [
                                    ft.OutlinedButton(
                                        "导出全部",
                                        icon=ft.Icons.DOWNLOAD_ROUNDED,
                                        tooltip="导出数据库、全部 Markdown 和历史记录",
                                        on_click=self.export_all_data,
                                        style=ft.ButtonStyle(
                                            shape=rounded(13),
                                            padding=16,
                                            side=ft.BorderSide(1, LINE),
                                            color=INK,
                                        ),
                                    ),
                                    ft.OutlinedButton(
                                        "导入备份",
                                        icon=ft.Icons.UPLOAD_FILE_ROUNDED,
                                        tooltip="校验完整备份后恢复整个工作空间",
                                        on_click=self.choose_import_backup,
                                        style=ft.ButtonStyle(
                                            shape=rounded(13),
                                            padding=16,
                                            side=ft.BorderSide(1, LINE),
                                            color=INK,
                                        ),
                                    ),
                                    ft.FilledButton(
                                        "新建主线",
                                        icon=ft.Icons.ADD_ROUNDED,
                                        on_click=self.open_blank_mainline,
                                        style=ft.ButtonStyle(
                                            shape=rounded(13),
                                            padding=18,
                                            bgcolor=INK,
                                            color=ft.Colors.WHITE,
                                        ),
                                    ),
                                ],
                                spacing=8,
                            ),
                        ],
                        spacing=16,
                    ),
                    self.vault_holder,
                ],
                spacing=26,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    def refresh_vault(self, *, update: bool = True) -> None:
        current_id = self.db.current_mainline_id()
        mainlines = [m for m in self.db.list_mainlines() if str(m["name"]) != "收集箱"]
        current = next(m for m in mainlines if int(m["id"]) == current_id)
        active = [m for m in mainlines if str(m["status"]) != "已归档"]
        other = [m for m in active if int(m["id"]) != current_id]
        archived = [m for m in mainlines if str(m["status"]) == "已归档"]

        current_stats = self.db.mainline_stats(current_id)
        controls: list[ft.Control] = [
            ft.Container(
                content=ft.Row(
                    [
                        ft.Container(width=7, height=58, bgcolor=BLUE, border_radius=99),
                        ft.Column(
                            [
                                ft.Row([pill("当前主线", color=BLUE, bgcolor=BLUE_SOFT), ft.Text(str(current["review_mode"] or "按需复盘"), size=13, color=MUTED)], spacing=10),
                                ft.Text(str(current["name"]), size=22, weight=ft.FontWeight.W_700, color=INK),
                                ft.Text(str(current["vision"] or ""), size=14, color=MUTED),
                            ],
                            spacing=5,
                            expand=True,
                        ),
                        ft.Column(
                            [
                                ft.Text(f"{int(current_stats['done'] or 0)}/{int(current_stats['total'] or 0)}", size=22, weight=ft.FontWeight.W_700, color=INK),
                                ft.Text("现实完成", size=12, color=MUTED),
                            ],
                            spacing=1,
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                        ),
                        ft.OutlinedButton(
                            "回到执行区",
                            icon=ft.Icons.ARROW_FORWARD_ROUNDED,
                            on_click=lambda _: self.show_view(self.NAV_CURRENT),
                            style=ft.ButtonStyle(shape=rounded(12), side=ft.BorderSide(1, LINE), color=INK),
                        ),
                        ft.IconButton(
                            ft.Icons.EDIT_NOTE_ROUNDED,
                            tooltip="打开主线记录",
                            icon_color=MUTED,
                            on_click=lambda _: self.open_mainline_editor(current_id),
                        ),
                        ft.IconButton(
                            ft.Icons.ARCHIVE_OUTLINED,
                            tooltip=(
                                "归档当前主线并切换到另一条主线"
                                if len(active) > 1
                                else "至少需要保留一条未归档主线"
                            ),
                            icon_color=MUTED,
                            disabled=len(active) <= 1,
                            on_click=lambda _: self.archive_mainline(current_id),
                        ),
                        ft.IconButton(
                            ft.Icons.DESCRIPTION_OUTLINED,
                            tooltip="打开主线 Markdown",
                            icon_color=MUTED,
                            on_click=lambda _: self.open_markdown("mainline", current_id),
                        ),
                    ],
                    spacing=16,
                ),
                padding=22,
                bgcolor=SURFACE,
                border=ft.Border.all(1, "#DCE5FA"),
                border_radius=20,
            ),
            ft.Row(
                [
                    section_title("保管中的主线", f"{len(other)} 条"),
                    pill("不会出现在执行区", color=MUTED, bgcolor="#F0F1F4", icon=ft.Icons.VISIBILITY_OFF_OUTLINED),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.ResponsiveRow(
                [self._vault_mainline_card(m) for m in other],
                spacing=16,
                run_spacing=16,
            ),
        ]
        if archived:
            controls.extend(
                [
                    ft.Row(
                        [
                            section_title("已归档", f"{len(archived)} 条"),
                            ft.Text("可以随时恢复，任务和文档不会删除", size=13, color=MUTED),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.ResponsiveRow(
                        [self._vault_mainline_card(m) for m in archived],
                        spacing=16,
                        run_spacing=16,
                    ),
                ]
            )
        self.vault_holder.controls = controls
        if update:
            self.page.update()

    def _vault_mainline_card(self, mainline) -> ft.Card:
        mid = int(mainline["id"])
        archived = str(mainline["status"]) == "已归档"
        stats = self.db.mainline_stats(mid)
        total = int(stats["total"] or 0)
        done = int(stats["done"] or 0)
        tasks = self.db.list_tasks(mid)
        previews = [str(t["title"]) for t in tasks if str(t["status"]) != "完成"][:3]
        task_controls: list[ft.Control] = []
        for title in previews:
            task_controls.append(
                ft.Row(
                    [
                        ft.Container(width=6, height=6, bgcolor="#BCC1CA", border_radius=99),
                        ft.Text(title, size=13, color="#555B66", expand=True, max_lines=1),
                    ],
                    spacing=9,
                )
            )
        if not task_controls:
            task_controls.append(ft.Text("没有待推进任务", size=13, color=MUTED))
        vision = str(mainline["vision"] or "").strip()
        summary_controls: list[ft.Control] = [
            ft.Row(
                [
                    ft.Container(width=10, height=10, bgcolor=str(mainline["color"] or BLUE), border_radius=99),
                    ft.Text(str(mainline["review_mode"] or "按需复盘"), size=12, color=MUTED),
                    ft.Container(expand=True),
                    ft.IconButton(
                        ft.Icons.EDIT_NOTE_ROUNDED,
                        tooltip="打开主线记录",
                        icon_color=MUTED,
                        on_click=lambda _, mainline_id=mid: self.open_mainline_editor(mainline_id),
                    ),
                ],
                spacing=8,
            ),
            ft.Text(str(mainline["name"] or "未命名主线"), size=20, weight=ft.FontWeight.W_700, color=INK, max_lines=2),
        ]
        if vision:
            summary_controls.append(ft.Text(vision, size=13, color=MUTED, max_lines=2))
        action_controls: list[ft.Control]
        if archived:
            action_controls = [
                ft.TextButton(
                    "打开记录",
                    icon=ft.Icons.EDIT_NOTE_ROUNDED,
                    on_click=lambda _, mainline_id=mid: self.open_mainline_editor(mainline_id),
                ),
                ft.OutlinedButton(
                    "恢复主线",
                    icon=ft.Icons.UNARCHIVE_OUTLINED,
                    on_click=lambda _, mainline_id=mid: self.restore_mainline(mainline_id),
                    style=ft.ButtonStyle(shape=rounded(12), color=BLUE, side=ft.BorderSide(1, "#C9D8FF")),
                ),
            ]
        else:
            action_controls = [
                ft.TextButton(
                    "查看任务",
                    icon=ft.Icons.LIST_ALT_ROUNDED,
                    on_click=lambda _, mainline_id=mid: self.open_mainline_tasks_dialog(mainline_id),
                ),
                ft.TextButton(
                    "归档",
                    icon=ft.Icons.ARCHIVE_OUTLINED,
                    on_click=lambda _, mainline_id=mid: self.archive_mainline(mainline_id),
                    style=ft.ButtonStyle(color=MUTED),
                ),
                ft.FilledButton(
                    "设为当前主线",
                    icon=ft.Icons.FLAG_ROUNDED,
                    on_click=lambda _, mainline_id=mid: self.activate_mainline(mainline_id),
                    style=ft.ButtonStyle(shape=rounded(12), bgcolor=BLUE, color=ft.Colors.WHITE),
                ),
            ]
        summary_controls.extend(
            [
                ft.Text(
                    f"待推进 {max(total - done, 0)}  ·  已完成 {done}",
                    size=13,
                    color=MUTED,
                ),
                ft.Divider(height=1, color=LINE),
                ft.Column(task_controls, spacing=9),
                ft.Row(
                    action_controls,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    wrap=True,
                ),
            ]
        )
        return ft.Card(
            content=ft.Container(
                content=ft.Column(summary_controls, spacing=13),
                padding=22,
            ),
            elevation=0,
            bgcolor="#FAFAFB" if archived else SURFACE,
            shape=rounded(20),
            variant=ft.CardVariant.OUTLINED,
            col={
                ft.ResponsiveRowBreakpoint.XS: 12,
                ft.ResponsiveRowBreakpoint.SM: 12,
                ft.ResponsiveRowBreakpoint.MD: 6,
                ft.ResponsiveRowBreakpoint.LG: 4,
                ft.ResponsiveRowBreakpoint.XL: 4,
                ft.ResponsiveRowBreakpoint.XXL: 4,
            },
        )

    def open_blank_mainline(self, _=None) -> None:
        self.selected_mainline_id = None
        self.content_switcher.content = self._blank_mainline_editor_view()
        self.page.update()

    def _blank_mainline_editor_view(self) -> ft.Container:
        """Let the user think on a blank page before a database row exists."""
        editor_height = max(560, min(780, float(self.page.height or 760) - 105))
        state: dict[str, int | None] = {"mainline_id": None}
        title_field = ft.TextField(
            hint_text="主线标题",
            hint_style=ft.TextStyle(size=26, color="#B4B7BE", weight=ft.FontWeight.W_600),
            border=ft.InputBorder.NONE,
            text_size=27,
            text_style=ft.TextStyle(weight=ft.FontWeight.W_700, color=INK),
            content_padding=0,
            autofocus=True,
        )
        body_field = ft.TextField(
            border=ft.InputBorder.NONE,
            multiline=True,
            min_lines=20,
            max_lines=35,
            text_size=16,
            content_padding=ft.Padding.only(top=8),
            expand=True,
        )
        saved_state = ft.Text("输入标题后自动保存", size=13, color=MUTED)

        def save(*, require_title: bool = False) -> int | None:
            title = str(title_field.value or "").strip()
            body = str(body_field.value or "")
            if not title:
                if require_title or body.strip():
                    title_field.error_text = "先给这条主线一个标题"
                    title_field.update()
                return None
            title_field.error_text = None
            mainline_id = state["mainline_id"]
            if mainline_id is None:
                mainline_id = self.db.create_mainline(title, body)
                state["mainline_id"] = mainline_id
                self.selected_mainline_id = mainline_id
            else:
                self.db.update_mainline(mainline_id, name=title, vision=body)
            self._sync_markdown()
            saved_state.value = "已自动保存"
            saved_state.update()
            return mainline_id

        def save_on_blur(_=None) -> None:
            save()

        def save_and_close(_=None) -> None:
            if not str(title_field.value or "").strip() and not str(body_field.value or "").strip():
                self.close_mainline_editor()
                return
            if save(require_title=True) is not None:
                self.close_mainline_editor()

        def save_and_activate(_=None) -> None:
            mainline_id = save(require_title=True)
            if mainline_id is not None:
                self.activate_mainline(mainline_id)

        def save_and_open_markdown(_=None) -> None:
            mainline_id = save(require_title=True)
            if mainline_id is not None:
                self.open_markdown("mainline", mainline_id)

        title_field.on_blur = save_on_blur
        body_field.on_blur = save_on_blur
        return self._page_shell(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.TextButton(
                                "返回主线保管箱",
                                icon=ft.Icons.ARROW_BACK_ROUNDED,
                                on_click=save_and_close,
                            ),
                            ft.Container(expand=True),
                            ft.Text("新主线", size=13, color=MUTED),
                        ]
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Container(title_field, expand=True),
                                        ft.OutlinedButton(
                                            "设为当前主线",
                                            icon=ft.Icons.FLAG_OUTLINED,
                                            on_click=save_and_activate,
                                            style=ft.ButtonStyle(
                                                color=BLUE,
                                                side=ft.BorderSide(1, "#C9D8FF"),
                                                shape=rounded(12),
                                            ),
                                        ),
                                    ],
                                    spacing=14,
                                    vertical_alignment=ft.CrossAxisAlignment.START,
                                ),
                                saved_state,
                                ft.Divider(height=1, color=LINE),
                                body_field,
                                ft.Row(
                                    [
                                        ft.TextButton(
                                            "打开 Markdown",
                                            icon=ft.Icons.DESCRIPTION_OUTLINED,
                                            on_click=save_and_open_markdown,
                                        ),
                                        ft.Text("没有标题时不会创建空记录", size=12, color=MUTED),
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                            ],
                            spacing=10,
                        ),
                        width=1040,
                        height=editor_height,
                        padding=24,
                        bgcolor=SURFACE,
                        border=ft.Border.all(1, LINE),
                        border_radius=18,
                    ),
                ],
                spacing=14,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    def open_mainline_editor(self, mainline_id: int, *, autofocus: bool = False) -> None:
        mainline = next(
            (item for item in self.db.list_mainlines() if int(item["id"]) == mainline_id),
            None,
        )
        if mainline is None:
            return
        self.selected_mainline_id = mainline_id
        self.content_switcher.content = self._mainline_editor_view(mainline, autofocus=autofocus)
        self.page.update()

    def close_mainline_editor(self) -> None:
        self.selected_mainline_id = None
        self.refresh_vault(update=False)
        self.content_switcher.content = self._vault_view()
        self.page.update()

    def _mainline_editor_view(self, mainline, *, autofocus: bool = False) -> ft.Container:
        mainline_id = int(mainline["id"])
        editor_height = max(560, min(780, float(self.page.height or 760) - 105))
        title_field = ft.TextField(
            value=str(mainline["name"] or ""),
            hint_text="主线标题",
            hint_style=ft.TextStyle(size=26, color="#B4B7BE", weight=ft.FontWeight.W_600),
            border=ft.InputBorder.NONE,
            text_size=27,
            text_style=ft.TextStyle(weight=ft.FontWeight.W_700, color=INK),
            content_padding=0,
            autofocus=autofocus,
        )
        body_field = ft.TextField(
            value=str(mainline["vision"] or ""),
            border=ft.InputBorder.NONE,
            multiline=True,
            min_lines=20,
            max_lines=35,
            text_size=16,
            content_padding=ft.Padding.only(top=8),
            expand=True,
        )

        def save(_=None) -> None:
            self.db.update_mainline(
                mainline_id,
                name=str(title_field.value or ""),
                vision=str(body_field.value or ""),
            )
            self._sync_markdown()

        def save_and_close(_=None) -> None:
            save()
            self.close_mainline_editor()

        def save_and_activate(_=None) -> None:
            save()
            self.activate_mainline(mainline_id)

        def save_and_open_markdown(_=None) -> None:
            save()
            self.open_markdown("mainline", mainline_id)

        def save_and_archive(_=None) -> None:
            save()
            self.archive_mainline(mainline_id)

        def save_and_restore(_=None) -> None:
            save()
            self.restore_mainline(mainline_id)

        title_field.on_blur = save
        body_field.on_blur = save
        is_current = mainline_id == self.db.current_mainline_id()
        is_archived = str(mainline["status"]) == "已归档"
        active_count = sum(
            1 for item in self.db.list_mainlines() if str(item["status"]) != "已归档"
        )
        can_archive = not is_current or active_count > 1
        return self._page_shell(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.TextButton(
                                "返回主线保管箱",
                                icon=ft.Icons.ARROW_BACK_ROUNDED,
                                on_click=save_and_close,
                            ),
                            ft.Container(expand=True),
                            ft.Text("主线记录", size=13, color=MUTED),
                        ]
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Container(title_field, expand=True),
                                        ft.OutlinedButton(
                                            "当前主线" if is_current else "设为当前主线",
                                            icon=ft.Icons.FLAG_ROUNDED if is_current else ft.Icons.FLAG_OUTLINED,
                                            disabled=is_current,
                                            on_click=save_and_activate,
                                            visible=not is_archived,
                                            style=ft.ButtonStyle(
                                                color=BLUE,
                                                side=ft.BorderSide(1, "#C9D8FF"),
                                                shape=rounded(12),
                                            ),
                                        ),
                                    ],
                                    spacing=14,
                                    vertical_alignment=ft.CrossAxisAlignment.START,
                                ),
                                ft.Text(
                                    f"创建于 {str(mainline['created_at'])[:16]}",
                                    size=13,
                                    color=MUTED,
                                ),
                                ft.Divider(height=1, color=LINE),
                                body_field,
                                ft.Row(
                                    [
                                        ft.TextButton(
                                            "打开 Markdown",
                                            icon=ft.Icons.DESCRIPTION_OUTLINED,
                                            on_click=save_and_open_markdown,
                                        ),
                                        ft.Row(
                                            [
                                                ft.Text("离开输入框时自动保存", size=12, color=MUTED),
                                                ft.TextButton(
                                                    "恢复主线" if is_archived else "归档主线",
                                                    icon=(
                                                        ft.Icons.UNARCHIVE_OUTLINED
                                                        if is_archived
                                                        else ft.Icons.ARCHIVE_OUTLINED
                                                    ),
                                                    on_click=(save_and_restore if is_archived else save_and_archive),
                                                    disabled=(not is_archived and not can_archive),
                                                    tooltip=(
                                                        "至少需要保留一条未归档主线"
                                                        if not is_archived and not can_archive
                                                        else None
                                                    ),
                                                    style=ft.ButtonStyle(color=MUTED),
                                                ),
                                            ],
                                            spacing=10,
                                            tight=True,
                                        ),
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                            ],
                            spacing=10,
                        ),
                        width=1040,
                        height=editor_height,
                        padding=24,
                        bgcolor=SURFACE,
                        border=ft.Border.all(1, LINE),
                        border_radius=18,
                    ),
                ],
                spacing=14,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    # --------------------------- Today / daily ledger ---------------------------

    def _refresh_local_day(self) -> None:
        """Move the live 'today' anchor after midnight without rewriting history."""
        real_today = date.today()
        if real_today == self._observed_local_day:
            self.today = real_today
            return
        self.db.refresh_today_flags()
        if self.selected_day == self._observed_local_day:
            self.selected_day = real_today
        if self.calendar_selected_day == self._observed_local_day:
            self.calendar_selected_day = real_today
            self.calendar_month = real_today.replace(day=1)
        self._observed_local_day = real_today
        self.today = real_today

    def _format_day_heading(self, value: date) -> str:
        real_today = date.today()
        if value == real_today:
            return "今天"
        if value == real_today - timedelta(days=1):
            return f"昨天 · {value.month}月{value.day}日"
        weekdays = "一二三四五六日"
        return f"{value.month}月{value.day}日 · 周{weekdays[value.weekday()]}"

    def _today_header(self) -> ft.Row:
        real_today = date.today()
        return ft.Row(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.CHECKLIST_ROUNDED, size=28, color=MUTED),
                        ft.Text(
                            self._format_day_heading(self.selected_day),
                            size=30,
                            weight=ft.FontWeight.W_700,
                            color=INK,
                        ),
                    ],
                    spacing=12,
                ),
                ft.Row(
                    [
                        ft.IconButton(
                            ft.Icons.SORT_ROUNDED,
                            tooltip="恢复默认排序" if self.today_priority_sort else "按优先级排序",
                            icon_color=BLUE if self.today_priority_sort else MUTED,
                            bgcolor=BLUE_SOFT if self.today_priority_sort else None,
                            on_click=self.toggle_today_sort,
                        ),
                        ft.IconButton(
                            ft.Icons.CHEVRON_LEFT_ROUNDED,
                            tooltip="前一天",
                            icon_color=MUTED,
                            on_click=lambda _: self.shift_selected_day(-1),
                        ),
                        ft.IconButton(
                            ft.Icons.CHEVRON_RIGHT_ROUNDED,
                            tooltip="后一天",
                            icon_color=MUTED,
                            disabled=self.selected_day >= real_today,
                            on_click=lambda _: self.shift_selected_day(1),
                        ),
                        ft.IconButton(
                            ft.Icons.CALENDAR_MONTH_ROUNDED,
                            tooltip="打开完成日历",
                            icon_color=MUTED,
                            on_click=lambda _: self.open_completion_calendar(self.selected_day),
                        ),
                    ],
                    spacing=2,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _today_view(self) -> ft.Container:
        selected_iso = self.selected_day.isoformat()
        real_today = date.today()
        is_today = self.selected_day == real_today
        entries = list(self.db.list_daily_entries(selected_iso))

        if is_today:
            overdue = list(self.db.list_overdue_entries(selected_iso))
            active = [row for row in entries if str(row["state"]) == "planned"]
            completed = [row for row in entries if str(row["state"]) == "completed"]
            unresolved: list = []
        else:
            overdue = []
            active = []
            completed = [row for row in entries if bool(row["had_completion"])]
            unresolved = [row for row in entries if not bool(row["had_completion"])]

        if self.today_priority_sort:
            rank = {"重要": 0, "普通": 1}
            sort_key = lambda row: (rank.get(str(row["priority"]), 2), str(row["entry_date"]), int(row["id"]))
            overdue.sort(key=sort_key)
            active.sort(key=sort_key)

        if is_today:
            input_or_history: ft.Control = ft.Container(
                self.quick_today_input,
                bgcolor="#F4F6F9",
                border_radius=16,
            )
        else:
            summary = self.db.daily_summary(selected_iso)
            done = int(summary["completed"] or 0) if summary else 0
            total = int(summary["total"] or 0) if summary else 0
            input_or_history = ft.Container(
                content=ft.Row(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.HISTORY_ROUNDED, size=19, color=MUTED),
                                ft.Text(
                                    f"历史账本 · 当天完成 {done}/{total} · 后续改名不会覆盖这里",
                                    size=14,
                                    color=MUTED,
                                ),
                            ],
                            spacing=9,
                        ),
                        ft.TextButton("回到今天", on_click=lambda _: self.go_to_today()),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=ft.Padding.symmetric(horizontal=18, vertical=8),
                bgcolor="#F5F6F8",
                border_radius=14,
            )

        groups: list[ft.Control] = []
        if overdue:
            groups.append(
                self._daily_group(
                    "已过期",
                    overdue,
                    overdue=True,
                    editable=True,
                    action_text="顺延到今天",
                    action=lambda _: self.postpone_overdue(overdue),
                )
            )
        if active:
            groups.append(self._daily_group("今天", active, editable=True))
        if unresolved:
            groups.append(self._daily_group("当日未完成", unresolved, editable=False))
        if completed:
            groups.append(
                self._daily_group(
                    "已完成",
                    completed,
                    completed=True,
                    editable=is_today,
                )
            )
        if not groups:
            groups.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(
                                ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
                                size=38,
                                color="#C2C6CE",
                            ),
                            ft.Text(
                                "今天还没有行动" if is_today else "这一天没有记录",
                                size=19,
                                weight=ft.FontWeight.W_700,
                                color=INK,
                            ),
                            ft.Text(
                                "在上方写下一个可以开始的最小行动。"
                                if is_today
                                else "可以继续查看相邻日期。",
                                size=14,
                                color=MUTED,
                            ),
                        ],
                        spacing=10,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding.only(top=54, bottom=54),
                    alignment=ft.Alignment.CENTER,
                )
            )

        body = ft.Container(
            content=ft.Column(
                [self._today_header(), input_or_history, *groups],
                spacing=18,
                scroll=ft.ScrollMode.AUTO,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            expand=True,
        )
        return self._page_shell(
            ft.Row(
                [body],
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )

    def _daily_group(
        self,
        title: str,
        entries,
        *,
        overdue: bool = False,
        completed: bool = False,
        editable: bool = False,
        action_text: str = "",
        action=None,
    ) -> ft.Control:
        collapsed = bool(self.today_collapsed.get(title, False))
        header_controls: list[ft.Control] = [
            ft.IconButton(
                ft.Icons.CHEVRON_RIGHT_ROUNDED if collapsed else ft.Icons.EXPAND_MORE_ROUNDED,
                tooltip="展开" if collapsed else "收起",
                icon_color="#9CA1AA",
                icon_size=20,
                on_click=lambda _, group=title: self.toggle_today_group(group),
            ),
            ft.Text(title, size=19, weight=ft.FontWeight.W_700, color=INK),
            ft.Text(str(len(entries)), size=14, color="#9CA1AA"),
            ft.Container(expand=True),
        ]
        if action_text:
            header_controls.append(
                ft.TextButton(
                    action_text,
                    icon=ft.Icons.UPDATE_ROUNDED,
                    on_click=action,
                    style=ft.ButtonStyle(color=BLUE),
                )
            )
        rows = [] if collapsed else [
            self._daily_entry_row(
                entry,
                overdue=overdue,
                completed=completed,
                editable=editable,
            )
            for entry in entries
        ]
        return ft.Column(
            [
                ft.Container(
                    ft.Row(header_controls, spacing=6),
                    padding=ft.Padding.only(top=4, bottom=2),
                ),
                *rows,
            ],
            spacing=0,
        )

    def _daily_entry_row(
        self,
        entry,
        *,
        overdue: bool,
        completed: bool,
        editable: bool,
    ) -> ft.Control:
        entry_id = int(entry["id"])
        task_id = int(entry["task_id"]) if entry["task_id"] else None
        mainline_color = str(entry["mainline_color"] or "#A6A9AE")
        checkbox_color = AMBER if str(entry["priority"]) == "重要" else mainline_color
        if completed:
            checkbox_color = "#C9CCD2"

        time_text = ""
        time_color = MUTED
        if completed:
            completion_value = (
                entry["last_completed_at"]
                if "last_completed_at" in entry.keys()
                else entry["completed_at"]
            )
            raw = str(completion_value or "")
            try:
                time_text = datetime.fromisoformat(raw).strftime("%H:%M")
            except ValueError:
                time_text = "已完成"
            time_color = "#C1C4CA"
        elif overdue:
            entry_day = str(entry["entry_date"])
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            time_text = "昨天" if entry_day == yesterday else entry_day[5:]
            time_color = RED
        elif str(entry["state"]) == "carried":
            time_text = "已结转"
            time_color = MUTED
        elif str(entry["entry_date"]) == date.today().isoformat():
            time_text = "今天"
            time_color = BLUE
        else:
            time_text = str(entry["entry_date"])[5:]

        meta: list[ft.Control] = [
            ft.Text(
                str(entry["mainline_name"] or "收集箱"),
                size=13,
                color="#C2C5CB" if completed else "#989DA6",
                max_lines=1,
            )
        ]
        if task_id is not None:
            meta.append(
                ft.IconButton(
                    ft.Icons.DESCRIPTION_OUTLINED,
                    tooltip="打开任务 Markdown",
                    icon_size=18,
                    icon_color="#CBCED4" if completed else "#A9AEB7",
                    on_click=lambda _, tid=task_id: self.open_markdown("task", tid),
                )
            )
        meta.append(ft.Text(time_text, size=13, color=time_color))

        checkbox = ft.Checkbox(
            value=completed,
            disabled=not editable,
            active_color=checkbox_color,
            check_color=ft.Colors.WHITE,
            on_change=(
                lambda e, eid=entry_id: self.set_today_entry_completed(
                    eid, bool(e.control.value)
                )
                if editable
                else None
            ),
        )
        return ft.Container(
            content=ft.Row(
                [
                    checkbox,
                    ft.Text(
                        str(entry["title"]),
                        size=16,
                        color="#B9BDC4" if completed else INK,
                        expand=True,
                        max_lines=2,
                    ),
                    ft.Row(meta, spacing=5, tight=True),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=68,
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            border=ft.Border.only(bottom=ft.BorderSide(1, LINE)),
        )

    def quick_add_today_task(self, event) -> None:
        title = str(event.control.value or "").strip()
        if not title:
            return
        inbox_id = self.db.get_or_create_inbox()
        self.db.create_task(
            inbox_id,
            title,
            status="今日",
            due_date=date.today().isoformat(),
            is_today=True,
        )
        self._sync_markdown()
        event.control.value = ""
        self.show_view(self.NAV_TODAY)

    def shift_selected_day(self, delta: int) -> None:
        self.selected_day = min(self.selected_day + timedelta(days=delta), date.today())
        self.show_view(self.NAV_TODAY)

    def go_to_today(self) -> None:
        self.selected_day = date.today()
        self._observed_local_day = date.today()
        self.show_view(self.NAV_TODAY)

    def toggle_today_sort(self, _=None) -> None:
        self.today_priority_sort = not self.today_priority_sort
        self.show_view(self.NAV_TODAY)

    def toggle_today_group(self, title: str) -> None:
        self.today_collapsed[title] = not self.today_collapsed.get(title, False)
        self.show_view(self.NAV_TODAY)

    def set_today_entry_completed(self, entry_id: int, completed: bool) -> None:
        self.db.set_daily_entry_completed(entry_id, completed)
        self._sync_markdown()
        self.calendar_selected_day = date.today()
        self.calendar_month = date.today().replace(day=1)
        self.show_view(self.NAV_TODAY)

    def postpone_overdue(self, entries) -> None:
        self.db.carry_daily_entries(
            (int(entry["id"]) for entry in entries),
            date.today().isoformat(),
        )
        self._sync_markdown()
        self.show_view(self.NAV_TODAY)

    # --------------------------- Completion calendar ---------------------------

    def open_completion_calendar(self, selected: date | None = None) -> None:
        if selected is not None:
            self.calendar_selected_day = min(selected, date.today())
            self.calendar_month = self.calendar_selected_day.replace(day=1)
        self.show_view(self.NAV_CALENDAR)

    def _completion_calendar_view(self) -> ft.Container:
        completion = self.db.completion_days(
            self.calendar_month.year,
            self.calendar_month.month,
            None,
        )
        total_completed = sum(completion.values())
        active_days = len(completion)
        header = ft.Row(
            [
                ft.Column(
                    [
                        ft.Text("完成日历", size=30, weight=ft.FontWeight.W_700, color=INK),
                        ft.Text(
                            "只记录现实发生过的完成事实，不计算连续天数。",
                            size=15,
                            color=MUTED,
                        ),
                    ],
                    spacing=5,
                ),
                pill(
                    f"本月完成 {total_completed} 项 · {active_days} 天有记录",
                    color=GREEN,
                    bgcolor=GREEN_SOFT,
                    icon=ft.Icons.CHECK_CIRCLE_ROUNDED,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        left = ft.Container(
            self._full_completion_calendar(completion),
            col={
                ft.ResponsiveRowBreakpoint.XS: 12,
                ft.ResponsiveRowBreakpoint.SM: 12,
                ft.ResponsiveRowBreakpoint.MD: 12,
                ft.ResponsiveRowBreakpoint.LG: 7,
                ft.ResponsiveRowBreakpoint.XL: 7,
                ft.ResponsiveRowBreakpoint.XXL: 7,
            },
        )
        right = ft.Container(
            self._completion_day_panel(),
            col={
                ft.ResponsiveRowBreakpoint.XS: 12,
                ft.ResponsiveRowBreakpoint.SM: 12,
                ft.ResponsiveRowBreakpoint.MD: 12,
                ft.ResponsiveRowBreakpoint.LG: 5,
                ft.ResponsiveRowBreakpoint.XL: 5,
                ft.ResponsiveRowBreakpoint.XXL: 5,
            },
        )
        body = ft.Container(
            ft.Column(
                [header, ft.ResponsiveRow([left, right], spacing=18, run_spacing=18)],
                spacing=24,
                scroll=ft.ScrollMode.AUTO,
            ),
            expand=True,
        )
        return self._page_shell(
            ft.Row([body], alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.START)
        )

    def _full_completion_calendar(self, completion: dict[str, int]) -> ft.Card:
        month = self.calendar_month
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(month.year, month.month)
        day_headers = [
            ft.Container(
                ft.Text(label, size=13, color=MUTED, text_align=ft.TextAlign.CENTER),
                col=1,
                alignment=ft.Alignment.CENTER,
            )
            for label in "一二三四五六日"
        ]
        cells: list[ft.Control] = []
        for week in weeks:
            for day_num in week:
                if not day_num:
                    cells.append(ft.Container(height=66, col=1))
                    continue
                value = date(month.year, month.month, day_num)
                day_iso = value.isoformat()
                count = int(completion.get(day_iso, 0))
                selected = value == self.calendar_selected_day
                is_today = value == date.today()
                future = value > date.today()
                cells.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(
                                    str(day_num),
                                    size=15,
                                    weight=ft.FontWeight.W_700 if selected or is_today else ft.FontWeight.W_500,
                                    color=(
                                        ft.Colors.WHITE
                                        if selected
                                        else "#C9CCD2"
                                        if future
                                        else BLUE
                                        if count or is_today
                                        else INK
                                    ),
                                ),
                                ft.Text(
                                    f"{count} 项" if count else "",
                                    size=11,
                                    color=ft.Colors.WHITE if selected else GREEN,
                                ),
                            ],
                            spacing=2,
                            alignment=ft.MainAxisAlignment.CENTER,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        height=66,
                        col=1,
                        bgcolor=BLUE if selected else GREEN_SOFT if count else "#00000000",
                        border=ft.Border.all(1, BLUE_SOFT if is_today and not selected else "#00000000"),
                        border_radius=14,
                        tooltip=f"{day_iso} · 完成 {count} 项" if count else day_iso,
                        on_click=(
                            None
                            if future
                            else self._guard_ui_action(
                                "选择完成日历日期失败",
                                lambda _, picked=value: self.select_completion_day(picked),
                                "无法查看这个日期",
                            )
                        ),
                    )
                )
        return ft.Card(
            content=ft.Container(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.IconButton(
                                    ft.Icons.CHEVRON_LEFT_ROUNDED,
                                    tooltip="上个月",
                                    icon_color=MUTED,
                                    on_click=self._guard_ui_action(
                                        "切换到上个月失败",
                                        lambda _: self.shift_completion_month(-1),
                                        "无法切换月份",
                                    ),
                                ),
                                ft.Text(
                                    f"{month.year} 年 {month.month} 月",
                                    size=20,
                                    weight=ft.FontWeight.W_700,
                                    color=INK,
                                ),
                                ft.IconButton(
                                    ft.Icons.CHEVRON_RIGHT_ROUNDED,
                                    tooltip="下个月",
                                    icon_color=MUTED,
                                    disabled=month >= date.today().replace(day=1),
                                    on_click=self._guard_ui_action(
                                        "切换到下个月失败",
                                        lambda _: self.shift_completion_month(1),
                                        "无法切换月份",
                                    ),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.ResponsiveRow(day_headers, columns=7, spacing=5),
                        ft.ResponsiveRow(cells, columns=7, spacing=5, run_spacing=5),
                        ft.Row(
                            [
                                ft.Container(width=8, height=8, bgcolor=GREEN, border_radius=99),
                                ft.Text("绿色表示当天有完成记录", size=12, color=MUTED),
                            ],
                            spacing=8,
                        ),
                    ],
                    spacing=15,
                ),
                padding=22,
            ),
            elevation=0,
            bgcolor=SURFACE,
            shape=rounded(20),
            variant=ft.CardVariant.OUTLINED,
        )

    def _completion_day_panel(self) -> ft.Card:
        day = self.calendar_selected_day
        completed = list(self.db.completed_entries_on(day.isoformat(), None))
        rows: list[ft.Control] = []
        for item in completed:
            raw = str(item["completed_at"] or "")
            try:
                time_text = datetime.fromisoformat(raw).strftime("%H:%M")
            except ValueError:
                time_text = ""
            rows.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                ft.Icon(ft.Icons.CHECK_ROUNDED, size=16, color=GREEN),
                                width=30,
                                height=30,
                                bgcolor=GREEN_SOFT,
                                border_radius=10,
                                alignment=ft.Alignment.CENTER,
                            ),
                            ft.Column(
                                [
                                    ft.Text(str(item["title"]), size=15, color=INK, max_lines=2),
                                    ft.Text(str(item["mainline_name"] or ""), size=12, color=MUTED),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.Text(time_text, size=12, color=MUTED),
                        ],
                        spacing=11,
                    ),
                    padding=ft.Padding.symmetric(horizontal=4, vertical=9),
                    border=ft.Border.only(bottom=ft.BorderSide(1, LINE)),
                )
            )
        if not rows:
            rows = [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.EVENT_AVAILABLE_OUTLINED, size=34, color="#C4C8D0"),
                            ft.Text("这一天还没有完成记录", size=15, color=MUTED),
                        ],
                        spacing=9,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding.symmetric(vertical=38),
                    alignment=ft.Alignment.CENTER,
                )
            ]
        return ft.Card(
            content=ft.Container(
                ft.Column(
                    [
                        ft.Text(
                            f"{day.month}月{day.day}日",
                            size=22,
                            weight=ft.FontWeight.W_700,
                            color=INK,
                        ),
                        ft.Text(f"完成 {len(completed)} 项", size=14, color=GREEN if completed else MUTED),
                        ft.Divider(height=1, color=LINE),
                        ft.Column(rows, spacing=0, scroll=ft.ScrollMode.AUTO),
                        ft.OutlinedButton(
                            "查看当天账本",
                            icon=ft.Icons.MENU_BOOK_OUTLINED,
                            on_click=self._guard_ui_action(
                                "打开每日日志失败",
                                lambda _: self.open_daily_ledger(day),
                                "无法打开这一天的日志",
                            ),
                            style=ft.ButtonStyle(shape=rounded(12), color=BLUE, side=ft.BorderSide(1, "#C9D8FF")),
                        ),
                    ],
                    spacing=12,
                ),
                padding=22,
            ),
            elevation=0,
            bgcolor=SURFACE,
            shape=rounded(20),
            variant=ft.CardVariant.OUTLINED,
        )

    def shift_completion_month(self, delta: int) -> None:
        index = self.calendar_month.year * 12 + self.calendar_month.month - 1 + delta
        year, month_zero = divmod(index, 12)
        candidate = date(year, month_zero + 1, 1)
        current_month = date.today().replace(day=1)
        if candidate > current_month:
            return
        self.calendar_month = candidate
        self.calendar_selected_day = date.today() if candidate == current_month else candidate
        self.show_view(self.NAV_CALENDAR)

    def select_completion_day(self, value: date) -> None:
        if value > date.today():
            return
        self.calendar_selected_day = value
        self.calendar_month = value.replace(day=1)
        self.show_view(self.NAV_CALENDAR)

    def open_daily_ledger(self, value: date) -> None:
        self.selected_day = min(value, date.today())
        self.show_view(self.NAV_TODAY)

    def _phase_placeholder(self, title: str, subtitle: str, icon) -> ft.Container:
        return self._page_shell(
            ft.Column(
                [
                    ft.Text(title, size=28, weight=ft.FontWeight.W_700, color=INK),
                    ft.Text(subtitle, size=16, color=MUTED),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Container(
                                    ft.Icon(icon, size=34, color=BLUE),
                                    width=62,
                                    height=62,
                                    bgcolor=BLUE_SOFT,
                                    border_radius=18,
                                    alignment=ft.Alignment.CENTER,
                                ),
                                ft.Text("Flet 迁移进行中", size=22, weight=ft.FontWeight.W_700, color=INK),
                                ft.Text("当前阶段先完成最关键的“当前主线 ↔ 保管箱”闭环，原版对应功能仍可继续使用。", size=14, color=MUTED, text_align=ft.TextAlign.CENTER),
                            ],
                            spacing=14,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        height=360,
                        bgcolor=SURFACE,
                        border=ft.Border.all(1, LINE),
                        border_radius=22,
                        alignment=ft.Alignment.CENTER,
                        padding=30,
                    ),
                ],
                spacing=20,
            )
        )

    def toggle_task(self, task_id: int, completed: bool) -> None:
        self.db.set_task_completed(task_id, completed)
        self._sync_markdown()
        self.refresh_current_sections()

    def focus_quick_input(self, _=None) -> None:
        self.page.run_task(self.quick_task_input.focus)

    def _set_quick_input_focus_style(self, focused: bool) -> None:
        self.quick_task_box.border = ft.Border.all(2 if focused else 1, BLUE if focused else LINE)
        self.quick_task_box.update()

    def quick_add_task(self, event) -> None:
        title = str(event.control.value or "").strip()
        if not title:
            return
        self.db.create_task(self.current_mid, title, is_today=True)
        self._sync_markdown()
        event.control.value = ""
        self.refresh_current_sections()
        self.page.run_task(self._restore_quick_input_focus)

    async def _restore_quick_input_focus(self) -> None:
        import asyncio

        await asyncio.sleep(0.05)
        await self.quick_task_input.focus()

    def select_task(self, task_id: int) -> None:
        task = self.db.get_task(task_id)
        if not task:
            return
        self.selected_task_id = task_id
        self.focus_holder.visible = False
        self.task_holder.controls = self._task_section(self.db.list_tasks(self.current_mid))
        self.detail_holder.content = self._task_detail_panel(task)
        self.page.update()

    def close_task_detail(self) -> None:
        self.selected_task_id = None
        self.focus_holder.visible = True
        self.task_holder.controls = self._task_section(self.db.list_tasks(self.current_mid))
        self.detail_holder.content = self.calendar_holder
        self.page.update()

    def set_focus_task(self, task_id: int) -> None:
        self.db.set_focus_task(task_id)
        self._sync_markdown()
        self.refresh_current_sections()

    def activate_mainline(self, mainline_id: int) -> None:
        self.db.set_current_mainline(mainline_id)
        self.current_mid = mainline_id
        self.selected_task_id = None
        self.quick_task_input.value = ""
        self.show_view(self.NAV_CURRENT)

    def archive_mainline(self, mainline_id: int) -> None:
        try:
            self.db.archive_mainline(mainline_id)
        except ValueError as error:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(str(error))))
            return
        self.selected_mainline_id = None
        self._sync_markdown()
        self.refresh_vault(update=False)
        self.content_switcher.content = self._vault_view()
        self.page.update()

    def restore_mainline(self, mainline_id: int) -> None:
        self.db.restore_mainline(mainline_id)
        self._sync_markdown()
        self.refresh_vault(update=False)
        self.content_switcher.content = self._vault_view()
        self.page.update()

    def open_markdown(self, kind: str, object_id: int) -> None:
        if not self._sync_markdown():
            return
        path = self.markdown.path_for(kind, object_id)
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                raise OSError("当前系统没有配置 Markdown 打开方式")
        except OSError as error:
            self._write_runtime_error("外部打开 Markdown 失败", traceback.format_exc())
            self._notify_error(f"无法打开 Markdown 文档：{error}")

    def open_mainline_tasks_dialog(self, mainline_id: int) -> None:
        mainline = next(m for m in self.db.list_mainlines() if int(m["id"]) == mainline_id)
        tasks = self.db.list_tasks(mainline_id)
        controls: list[ft.Control] = []
        for task in tasks:
            done = str(task["status"]) == "完成"
            controls.append(
                ft.ListTile(
                    leading=ft.Icon(
                        ft.Icons.CHECK_CIRCLE_ROUNDED if done else ft.Icons.RADIO_BUTTON_UNCHECKED_ROUNDED,
                        color=GREEN if done else MUTED,
                    ),
                    title=ft.Text(str(task["title"]), size=15, color="#A5A9B2" if done else INK),
                    subtitle=ft.Text(str(task["next_action"] or task["status"]), size=12, color=MUTED),
                    trailing=ft.IconButton(
                        ft.Icons.DESCRIPTION_OUTLINED,
                        tooltip="打开 Markdown",
                        on_click=lambda _, tid=int(task["id"]): self.open_markdown("task", tid),
                    ),
                )
            )
        if not controls:
            controls.append(ft.Text("这条主线还没有任务。", size=14, color=MUTED))
        self.page.show_dialog(
            ft.AlertDialog(
                title=ft.Text(str(mainline["name"]), size=22, weight=ft.FontWeight.W_700),
                content=ft.Column(controls, spacing=6, width=560, scroll=ft.ScrollMode.AUTO),
                actions=[ft.FilledButton("关闭", on_click=lambda _: self._close_dialog())],
                shape=rounded(20),
                scrollable=True,
            )
        )

    def _close_dialog(self) -> None:
        self.page.pop_dialog()

    async def export_all_data(self, _=None) -> None:
        if not self._sync_markdown():
            return
        try:
            selected_path = await self.file_picker.save_file(
                dialog_title="导出 ENTP 完整备份",
                file_name=default_backup_name(),
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["zip"],
            )
            if not selected_path:
                return
            target = Path(selected_path)
            if target.suffix.lower() != ".zip":
                target = target.with_name(f"{target.name}.entp.zip")
            summary = export_workspace(self.db, self.markdown.root, target)
        except BackupError as error:
            self._write_runtime_error("导出完整备份失败", traceback.format_exc())
            self._notify_error(str(error))
            return
        except Exception as error:
            self._write_runtime_error("导出完整备份发生意外错误", traceback.format_exc())
            self._notify_error(f"无法导出完整备份：{error}")
            return
        self._notify_success(
            f"完整备份已保存：{summary.mainlines} 条主线、{summary.tasks} 个任务、"
            f"{summary.thoughts} 条灵感、{summary.markdown_files} 个 Markdown。\n"
            f"{summary.archive_path}"
        )

    async def choose_import_backup(self, _=None) -> None:
        try:
            files = await self.file_picker.pick_files(
                dialog_title="选择 ENTP 完整备份",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["zip"],
                allow_multiple=False,
            )
            if not files:
                return
            selected_path = getattr(files[0], "path", None)
            if not selected_path:
                raise BackupError("无法读取所选文件的本地路径")
            archive_path = Path(selected_path).resolve()
            summary = inspect_backup(archive_path)
        except BackupError as error:
            self._write_runtime_error("检查导入备份失败", traceback.format_exc())
            self._notify_error(str(error))
            return
        except Exception as error:
            self._write_runtime_error("选择导入备份发生意外错误", traceback.format_exc())
            self._notify_error(f"无法读取这个备份：{error}")
            return
        self.show_import_confirmation(archive_path, summary)

    def show_import_confirmation(
        self, archive_path: Path, summary: BackupSummary
    ) -> None:
        created_at = summary.created_at.replace("T", " ")[:19] or "未知时间"

        async def confirm_import(_) -> None:
            await self.confirm_import_backup(archive_path)

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Row(
                    [
                        ft.Container(
                            ft.Icon(ft.Icons.RESTORE_ROUNDED, size=25, color=BLUE),
                            width=46,
                            height=46,
                            alignment=ft.Alignment.CENTER,
                            bgcolor=BLUE_SOFT,
                            border_radius=14,
                        ),
                        ft.Column(
                            [
                                ft.Text("恢复完整工作空间", size=22, weight=ft.FontWeight.W_700),
                                ft.Text("备份已通过完整性与安全校验", size=13, color=GREEN),
                            ],
                            spacing=2,
                        ),
                    ],
                    spacing=12,
                ),
                content=ft.Column(
                    [
                        ft.Container(
                            content=ft.ResponsiveRow(
                                [
                                    self._backup_stat("主线", summary.mainlines),
                                    self._backup_stat("任务", summary.tasks),
                                    self._backup_stat("灵感", summary.thoughts),
                                    self._backup_stat("Markdown", summary.markdown_files),
                                ],
                                spacing=8,
                                run_spacing=8,
                            ),
                            padding=14,
                            bgcolor="#F7F8FB",
                            border_radius=15,
                        ),
                        ft.Text(f"备份时间：{created_at}", size=13, color=MUTED),
                        ft.Text(
                            f"文件：{archive_path.name}",
                            size=13,
                            color=MUTED,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, size=20, color=AMBER),
                                    ft.Text(
                                        "导入会整体替换当前数据，不会把两份任务混在一起。\n"
                                        "开始前会自动导出一份当前工作空间，可随时恢复。",
                                        size=14,
                                        color="#59451D",
                                        expand=True,
                                    ),
                                ],
                                spacing=10,
                            ),
                            padding=14,
                            bgcolor=AMBER_SOFT,
                            border_radius=14,
                        ),
                    ],
                    width=590,
                    spacing=14,
                    tight=True,
                ),
                actions=[
                    ft.TextButton("取消", on_click=lambda _: self._close_dialog()),
                    ft.FilledButton(
                        "自动备份并导入",
                        icon=ft.Icons.RESTORE_ROUNDED,
                        on_click=confirm_import,
                        style=ft.ButtonStyle(
                            shape=rounded(12),
                            padding=16,
                            bgcolor=BLUE,
                            color=ft.Colors.WHITE,
                        ),
                    ),
                ],
                shape=rounded(22),
            )
        )

    @staticmethod
    def _backup_stat(label: str, value: int) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(str(value), size=20, weight=ft.FontWeight.W_700, color=INK),
                    ft.Text(label, size=12, color=MUTED),
                ],
                spacing=1,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=9),
            bgcolor=SURFACE,
            border_radius=12,
            col={ft.ResponsiveRowBreakpoint.XS: 6, ft.ResponsiveRowBreakpoint.SM: 3},
        )

    async def confirm_import_backup(self, archive_path: Path) -> None:
        self._close_dialog()
        if not self._sync_markdown():
            return
        database_path = self.db.path.resolve()
        markdown_root = self.markdown.root.resolve()
        safety_dir = ROOT / "backups"
        safety_path = safety_dir / (
            f"导入前自动备份_{datetime.now():%Y%m%d_%H%M%S}.entp.zip"
        )
        safety_created = False
        try:
            export_workspace(self.db, markdown_root, safety_path)
            safety_created = True
            self._close_database()
            restore_workspace(archive_path, database_path, markdown_root)
            self._reopen_workspace(database_path, markdown_root)
            self._reset_workspace_view_state()
            self._sync_markdown(show_error=False)
            self.show_view(self.NAV_CURRENT)
        except Exception as error:
            self._write_runtime_error("导入完整备份失败", traceback.format_exc())
            if self._closed:
                try:
                    self._reopen_workspace(database_path, markdown_root)
                    self._reset_workspace_view_state()
                    self.show_view(self.NAV_VAULT)
                except Exception:
                    self._write_runtime_error("导入失败后重新连接工作空间失败", traceback.format_exc())
            message = str(error) if isinstance(error, BackupError) else f"导入失败：{error}"
            recovery_note = (
                f"。当前数据的安全备份位于：{safety_path}"
                if safety_created
                else "。当前数据没有被替换"
            )
            self._notify_error(f"{message}{recovery_note}")
            return
        self._notify_success(
            f"完整工作空间已恢复。导入前的数据也已保存在：{safety_path}"
        )

    def open_execution_dialog(self, task_id: int) -> None:
        action = ft.TextField(label="我实际做了什么", autofocus=True, multiline=True, min_lines=2, max_lines=4, text_size=15, border_radius=12)
        result = ft.TextField(label="产生了什么结果 / 发现", multiline=True, min_lines=2, max_lines=4, text_size=15, border_radius=12)
        next_action = ft.TextField(label="接下来最小的一步（可选）", text_size=15, border_radius=12)
        complete = ft.Checkbox(label="这项任务已经现实完成", value=False, active_color=GREEN)

        def save(_) -> None:
            if not action.value.strip():
                action.error = "请写下实际行动"
                action.update()
                return
            self.db.add_task_execution_log(
                task_id,
                action=action.value,
                result=result.value,
                next_action=next_action.value,
                complete=bool(complete.value),
            )
            self._sync_markdown()
            self._close_dialog()
            self.refresh_current_sections()

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("记录一次现实执行", size=22, weight=ft.FontWeight.W_700),
                content=ft.Column([action, result, next_action, complete], tight=True, spacing=13, width=560),
                actions=[ft.TextButton("取消", on_click=lambda _: self._close_dialog()), ft.FilledButton("保存记录", on_click=save)],
                shape=rounded(20),
                scrollable=True,
            )
        )

    def open_stuck_dialog(self, task_id: int) -> None:
        # “卡住”在这里指好奇心降低，不是任务发生了技术阻塞。
        # 直接进入独立候审池，让用户自由审视任何灵感。
        self.selected_thought_id = None
        self.show_view(self.NAV_IDEAS)
        self.open_first_unreviewed()

    def save_quick_inspiration(self, title: str, raw_content: str = "") -> int:
        """Capture curiosity without forcing it to belong to the current mainline."""
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("灵感标题不能为空")
        thought_id = self.db.create_thought(
            clean_title,
            raw_content.strip(),
            None,
        )
        self._sync_markdown()
        return thought_id

    def _inline_inspiration_capture(self) -> ft.Control:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(self.inline_inspiration_input, expand=True),
                    ft.IconButton(
                        ft.Icons.CLOSE_ROUNDED,
                        tooltip="收起",
                        icon_color=MUTED,
                        on_click=self.close_inline_inspiration,
                    ),
                ],
                spacing=4,
            ),
            padding=ft.Padding.only(left=4, right=5),
            bgcolor=AMBER_SOFT,
            border=ft.Border.all(1, "#F0D8A1"),
            border_radius=14,
        )

    def open_inline_inspiration(self, _=None) -> None:
        self.inspiration_capture_open = True
        self.inline_inspiration_input.value = ""
        self.refresh_current_sections()
        self.page.run_task(self._focus_inline_inspiration)

    async def _focus_inline_inspiration(self) -> None:
        import asyncio

        await asyncio.sleep(0.05)
        await self.inline_inspiration_input.focus()

    def close_inline_inspiration(self, _=None) -> None:
        self.inspiration_capture_open = False
        self.inline_inspiration_input.value = ""
        self.refresh_current_sections()

    def quick_capture_inspiration(self, event) -> None:
        title = str(event.control.value or "").strip()
        if not title:
            self.close_inline_inspiration()
            return
        self.save_quick_inspiration(title)
        self.inspiration_capture_open = False
        self.inline_inspiration_input.value = ""
        self.refresh_current_sections()

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ENTP 自强手册 Flet 2.0")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--view",
        choices=("current", "vault", "ideas", "today", "calendar"),
        default="current",
    )
    parser.add_argument("--qa-day", type=date.fromisoformat)
    parser.add_argument("--qa-screenshot", type=Path)
    parser.add_argument("--qa-compact", action="store_true")
    parser.add_argument("--qa-task-detail", action="store_true")
    parser.add_argument("--qa-quick-add", action="store_true")
    parser.add_argument("--qa-input-focus", action="store_true")
    parser.add_argument("--qa-add-inspiration", action="store_true")
    parser.add_argument("--qa-inspiration-dialog", action="store_true")
    parser.add_argument("--qa-idea-detail", action="store_true")
    parser.add_argument("--qa-mainline-editor", action="store_true")
    parser.add_argument("--qa-archive-mainline", action="store_true")
    parser.add_argument("--qa-import-file", type=Path)
    parser.add_argument("--qa-boundary-report", type=Path)
    parser.add_argument("--qa-boundary-error", action="store_true")
    parser.add_argument("--qa-execution-dialog", action="store_true")
    parser.add_argument("--qa-runtime-error", action="store_true")
    return parser.parse_args()


def capture_window(title: str, target: Path) -> None:
    import time

    from PIL import ImageGrab

    candidates: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def enum_windows(hwnd, _lparam):
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
            candidates.append((int(hwnd), buffer.value))
        return True

    ctypes.windll.user32.EnumWindows(enum_windows, 0)
    hwnd = next((h for h, caption in candidates if title in caption), 0)
    if not hwnd:
        (target.parent / "flet-window-titles.txt").write_text(
            "\n".join(caption for _, caption in candidates), encoding="utf-8"
        )
        return
    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    ctypes.windll.user32.ShowWindow(hwnd, 9)
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(0.35)
    ctypes.windll.user32.SetCursorPos(rect.left + 30, rect.top + 420)
    time.sleep(0.25)
    target.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True).save(target)


def main() -> None:
    args = parse_args()

    async def app_main(page: ft.Page) -> None:
        try:
            import asyncio

            ui = EntpFletApp(page, args.db.resolve(), args.view)
            if args.qa_compact:
                page.window.maximized = False
                page.update()
                await asyncio.sleep(0.4)
                page.window.width = 920
                page.window.height = 720
                page.update()
                await asyncio.sleep(1.0)
            if args.view == "vault":
                await asyncio.sleep(0.6)
                if args.qa_import_file:
                    archive_path = args.qa_import_file.resolve()
                    ui.show_import_confirmation(
                        archive_path,
                        inspect_backup(archive_path),
                    )
                elif args.qa_mainline_editor:
                    ui.open_blank_mainline()
                elif args.qa_archive_mainline:
                    current_id = ui.db.current_mainline_id()
                    target = next(
                        (
                            item
                            for item in ui.db.list_mainlines()
                            if int(item["id"]) != current_id
                            and str(item["status"]) != "已归档"
                        ),
                        None,
                    )
                    if target is not None:
                        ui.archive_mainline(int(target["id"]))
            elif args.view == "ideas":
                await asyncio.sleep(0.6)
                ui.show_view(ui.NAV_IDEAS)
                if args.qa_idea_detail:
                    target = next(iter(ui.db.list_thoughts()), None)
                    if target is not None:
                        ui.open_thought_review(int(target["id"]))
            elif args.view == "today":
                await asyncio.sleep(0.6)
                if args.qa_day:
                    ui.selected_day = min(args.qa_day, date.today())
                ui.show_view(ui.NAV_TODAY)
            elif args.view == "calendar":
                await asyncio.sleep(0.6)
                if args.qa_day:
                    ui.calendar_selected_day = min(args.qa_day, date.today())
                    ui.calendar_month = ui.calendar_selected_day.replace(day=1)
                ui.show_view(ui.NAV_CALENDAR)
            elif args.qa_quick_add:
                from types import SimpleNamespace

                ui.quick_task_input.value = "QA 快速输入任务"
                ui.quick_add_task(SimpleNamespace(control=ui.quick_task_input))
                await asyncio.sleep(0.4)
            if args.qa_input_focus:
                await ui.quick_task_input.focus()
                await asyncio.sleep(0.5)
            if args.qa_add_inspiration:
                ui.save_quick_inspiration(
                    "QA 当前主线灵感",
                    "验证灵感只进入独立候审区，默认不关联任何主线。",
                )
                await asyncio.sleep(0.3)
            if args.qa_inspiration_dialog:
                ui.open_inline_inspiration()
                await asyncio.sleep(0.5)
            if args.qa_runtime_error:
                from types import SimpleNamespace

                ui._handle_page_error(SimpleNamespace(data="database is locked"))
                await asyncio.sleep(0.5)
            if args.view != "vault" and args.qa_task_detail:
                await asyncio.sleep(0.4)
                target = next(
                    (
                        task
                        for task in ui.db.list_tasks(ui.current_mid)
                        if str(task["status"]) != "完成"
                    ),
                    None,
                )
                if target is not None:
                    ui.select_task(int(target["id"]))
            if args.qa_execution_dialog:
                target = next(iter(ui.db.list_tasks(ui.current_mid)), None)
                if target is not None:
                    ui.open_execution_dialog(int(target["id"]))
            if args.qa_boundary_error:
                def force_isolated_failure(_event) -> None:
                    ui.active_index = ui.NAV_CALENDAR
                    ui.db.conn.execute(
                        "UPDATE app_settings SET value = value WHERE key = ?",
                        ("current_mainline_id",),
                    )
                    raise RuntimeError("QA isolated interaction failure")

                probe = ft.FilledButton("异常边界探针", on_click=force_isolated_failure)
                ui._protect_control_tree(probe)
                probe.on_click(None)
                await asyncio.sleep(0.5)
            if args.qa_boundary_report:
                page.update()
                await asyncio.sleep(0.3)
                total, unprotected = ui.interaction_boundary_audit()
                report_path = args.qa_boundary_report.resolve()
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(
                    f"handlers={total}\nunprotected={len(unprotected)}\n"
                    + "\n".join(unprotected),
                    encoding="utf-8",
                )
            if args.qa_screenshot:
                qa_title = f"ENTP 自强手册 2.0 · QA · {args.view}"
                page.title = qa_title
                page.update()
                await asyncio.sleep(3.5)
                (args.qa_screenshot.parent / "flet-qa-dimensions.txt").write_text(
                    f"page={page.width}x{page.height}\nwindow={page.window.width}x{page.window.height}\n",
                    encoding="utf-8",
                )
                target = args.qa_screenshot.resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(await page.take_screenshot(pixel_ratio=1.0))
                await page.window.close()
        except Exception:
            import traceback

            (ROOT / "logs" / "flet-startup-error.log").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            try:
                await page.window.close()
            except Exception:
                pass
            raise

    ft.run(app_main, assets_dir=str(ROOT / "assets"))


if __name__ == "__main__":
    main()
