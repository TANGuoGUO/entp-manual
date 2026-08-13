from __future__ import annotations

import argparse
import calendar
import ctypes
import os
import shutil
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

VENDOR_DIR = Path(__file__).with_name("vendor")
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    import markdown2
    from tkinterweb import HtmlFrame
except ImportError:  # The source editor remains available without optional preview packages.
    markdown2 = None
    HtmlFrame = None

from database import (
    Database,
    RELATION_TYPES,
    TASK_STATUSES,
    THOUGHT_STATUSES,
)
from markdown_store import MarkdownStore


BG = "#FFFFFF"
TEXT = "#17191F"
MUTED = "#747A84"
BORDER = "#E5E7EB"
SHADOW = "#EDEFF2"
BLUE = "#1976E9"
BLUE_SOFT = "#EAF3FF"
SIDEBAR = "#FBFBFC"
GRAY_SOFT = "#F5F6F7"
YELLOW = "#EBAE3C"
YELLOW_SOFT = "#FFF9ED"
GREEN = "#289A70"
GREEN_SOFT = "#EEF9F4"
ROSE = "#D95779"
ROSE_SOFT = "#FFF4F6"

FONT = "Microsoft YaHei UI"
FONT_FALLBACK = "Segoe UI"
ICON_FONT = "Segoe MDL2 Assets"

APP_ROOT = Path(__file__).resolve().parent
LOG_DIR = APP_ROOT / "logs"


def write_log(filename: str, message: str) -> None:
    """Best-effort persistent diagnostics for windowless desktop launches."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with (LOG_DIR / filename).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"[{timestamp}] {message.rstrip()}\n")
    except OSError:
        pass


def clear(widget: tk.Misc) -> None:
    for child in widget.winfo_children():
        child.destroy()


def bind_click(widget: tk.Misc, callback: Callable) -> None:
    widget.bind("<Button-1>", callback)
    for child in widget.winfo_children():
        bind_click(child, callback)


def _rounded_polygon(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs):
    radius = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = (
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
    )
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


class RoundedSurface(tk.Canvas):
    """A native Tk container with rounded corners and restrained elevation."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        fill: str = BG,
        border: str = BORDER,
        radius: int = 12,
        shadow: bool = False,
        padding: int = 1,
        height: int | None = None,
        cursor: str = "arrow",
    ) -> None:
        parent_bg = str(parent.cget("bg")) if "bg" in parent.keys() else BG
        super().__init__(
            parent,
            bg=parent_bg,
            bd=0,
            highlightthickness=0,
            height=height or 1,
            cursor=cursor,
        )
        self.fill_color = fill
        self.border_color = border
        self.radius = radius
        self.with_shadow = shadow
        self.padding = padding + (3 if shadow else 1)
        self.fixed_height = height
        self.inner = tk.Frame(self, bg=fill, bd=0, highlightthickness=0)
        self._window = self.create_window(self.padding, self.padding, anchor="nw", window=self.inner)
        self.bind("<Configure>", self._redraw)
        self.inner.bind("<Configure>", self._fit_height, add="+")
        self.after_idle(self._fit_height)

    def _fit_height(self, _event=None) -> None:
        if self.fixed_height is None:
            wanted = max(1, self.inner.winfo_reqheight() + self.padding * 2)
            if int(float(self.cget("height"))) != wanted:
                self.configure(height=wanted)

    def _redraw(self, event=None) -> None:
        width = event.width if event else self.winfo_width()
        height = event.height if event else self.winfo_height()
        self.delete("surface")
        if self.with_shadow:
            _rounded_polygon(
                self, 2, 3, width - 2, height - 1, self.radius,
                fill=SHADOW, outline="", tags="surface",
            )
        bottom = height - (3 if self.with_shadow else 1)
        _rounded_polygon(
            self, 1, 1, width - 1, bottom, self.radius,
            fill=self.fill_color, outline=self.border_color, width=1, tags="surface",
        )
        self.tag_lower("surface")
        self.coords(self._window, self.padding, self.padding)
        window_options = {"width": max(1, width - self.padding * 2)}
        if self.fixed_height is not None:
            window_options["height"] = max(1, height - self.padding * 2)
        self.itemconfigure(self._window, **window_options)


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable,
        *,
        bg: str,
        fg: str,
        active_bg: str,
        width: int | None = None,
        height: int = 42,
        radius: int = 10,
        font: tuple = (FONT, 10),
        anchor: str = "center",
        padx: int = 15,
        icon: str = "",
    ) -> None:
        parent_bg = str(parent.cget("bg")) if "bg" in parent.keys() else BG
        font_obj = tkfont.Font(font=font)
        icon_font = tkfont.Font(family=ICON_FONT, size=font[1])
        icon_width = icon_font.measure(icon) + 8 if icon else 0
        pixel_width = width or max(44, font_obj.measure(text) + icon_width + padx * 2)
        super().__init__(
            parent, width=pixel_width, height=height, bg=parent_bg,
            bd=0, highlightthickness=0, cursor="hand2",
        )
        self.label = text
        self.command = command
        self.normal_bg = bg
        self.active_bg = active_bg
        self.fg = fg
        self.radius = radius
        self.pixel_height = height
        self.font_spec = font
        self.anchor = anchor
        self.padx = padx
        self.icon = icon
        self.bind("<Configure>", self._draw_normal)
        self.bind("<Map>", self._queue_normal_draw)
        self.bind("<Enter>", self._draw_active)
        self.bind("<Leave>", self._draw_normal)
        self.bind("<ButtonRelease-1>", lambda _e: self.command())
        # Tk can report an early, shorter canvas size while a packed row is still
        # negotiating its height. Redraw once the containing layout has settled.
        self.after(120, self._draw_normal)

    def _draw_normal(self, _event=None) -> None:
        if self.winfo_exists():
            self._draw(self.normal_bg)

    def _queue_normal_draw(self, _event=None) -> None:
        if self.winfo_exists():
            self.after_idle(self._draw_normal)

    def _draw_active(self, _event=None) -> None:
        if self.winfo_exists():
            self._draw(self.active_bg)

    def _draw(self, fill: str) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = max(self.winfo_height(), self.pixel_height)
        _rounded_polygon(self, 1, 1, width - 1, height - 1, self.radius, fill=fill, outline="")
        icon_width = 0
        if self.icon:
            icon_width = tkfont.Font(family=ICON_FONT, size=self.font_spec[1]).measure(self.icon) + 8
        if self.anchor == "w":
            x, text_anchor = self.padx + icon_width, "w"
            icon_x = self.padx
        else:
            label_width = tkfont.Font(font=self.font_spec).measure(self.label)
            icon_x = (width - label_width - icon_width) / 2
            x, text_anchor = icon_x + icon_width, "w"
        if self.icon:
            self.create_text(
                icon_x, height / 2, text=self.icon, fill=self.fg,
                font=(ICON_FONT, self.font_spec[1]), anchor="w",
            )
        self.create_text(
            x, height / 2, text=self.label, fill=self.fg,
            font=self.font_spec, anchor=text_anchor,
        )


class RoundedInput:
    """Small proxy that keeps Entry/Text behavior while giving fields rounded chrome."""

    def __init__(self, parent: tk.Misc, *, multiline: bool = False, textvariable=None, height: int = 4) -> None:
        self.surface = RoundedSurface(
            parent, fill=BG, border="#DDE1E6", radius=10, shadow=False, padding=5
        )
        if multiline:
            self.widget = tk.Text(
                self.surface.inner,
                height=height,
                wrap="word",
                bg=BG,
                fg=TEXT,
                insertbackground=TEXT,
                relief="flat",
                bd=0,
                highlightthickness=0,
                padx=7,
                pady=5,
                font=(FONT, 11),
                spacing1=2,
                spacing3=2,
            )
        else:
            self.widget = tk.Entry(
                self.surface.inner,
                textvariable=textvariable,
                bg=BG,
                fg=TEXT,
                insertbackground=TEXT,
                relief="flat",
                bd=0,
                highlightthickness=0,
                font=(FONT, 10),
            )
        self.widget.pack(fill="both", expand=True)
        self.widget.bind("<FocusIn>", lambda _e: self._focus_border(BLUE), add="+")
        self.widget.bind("<FocusOut>", lambda _e: self._focus_border("#DDE1E6"), add="+")

    def _focus_border(self, color: str) -> None:
        self.surface.border_color = color
        self.surface._redraw()

    def pack(self, *args, **kwargs):
        return self.surface.pack(*args, **kwargs)

    def grid(self, *args, **kwargs):
        return self.surface.grid(*args, **kwargs)

    def place(self, *args, **kwargs):
        return self.surface.place(*args, **kwargs)

    def configure(self, **kwargs):
        return self.widget.configure(**kwargs)

    config = configure

    def bind(self, *args, **kwargs):
        return self.widget.bind(*args, **kwargs)

    def get(self, *args, **kwargs):
        return self.widget.get(*args, **kwargs)

    def insert(self, *args, **kwargs):
        return self.widget.insert(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return self.widget.delete(*args, **kwargs)

    def focus_set(self):
        return self.widget.focus_set()


def button(
    parent: tk.Misc,
    text: str,
    command: Callable,
    *,
    primary: bool = False,
    subtle: bool = False,
    width: int | None = None,
    icon: str = "",
) -> RoundedButton:
    bg = BLUE if primary else (GRAY_SOFT if subtle else BG)
    fg = "white" if primary else TEXT
    active_bg = "#1269D2" if primary else "#EEF0F2"
    pixel_width = None if width is None else max(38, width * 12 + 12)
    return RoundedButton(
        parent, text, command, width=pixel_width, bg=bg, fg=fg,
        active_bg=active_bg, radius=11, height=42,
        font=(FONT, 11, "bold" if primary else "normal"),
        icon=icon,
    )


def entry(parent: tk.Misc, textvariable: tk.Variable | None = None) -> RoundedInput:
    return RoundedInput(parent, textvariable=textvariable)


def text_box(parent: tk.Misc, value: str = "", height: int = 4) -> RoundedInput:
    widget = RoundedInput(parent, multiline=True, height=height)
    widget.insert("1.0", value or "")
    return widget


class ScrollFrame(tk.Frame):
    def __init__(self, parent: tk.Misc, *, bg: str = BG, **kwargs) -> None:
        super().__init__(parent, bg=bg, **kwargs)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")

    def _on_body(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self.window, width=event.width)

    def _on_wheel(self, event) -> None:
        try:
            x = self.winfo_pointerx()
            y = self.winfo_pointery()
            hovered = self.winfo_containing(x, y)
            if hovered and str(hovered).startswith(str(self)):
                self.canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass


class ENTPManualApp(tk.Tk):
    def __init__(self, db_path: Path) -> None:
        super().__init__()
        # A comfortable desktop reading baseline. Layout breakpoints handle space;
        # typography should not shrink merely because the window gets narrower.
        self.tk.call("tk", "scaling", 1.55)
        self.db = Database(db_path)
        self.markdown = MarkdownStore(Path(db_path).parent / "markdown")
        self.markdown.sync_all(self.db)
        self.title("ENTP 自强手册 2.0")
        self.geometry("1500x920")
        self.minsize(1180, 720)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "TCombobox",
            fieldbackground=BG,
            background=BG,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=7,
            font=(FONT, 10),
        )
        style.map("TCombobox", fieldbackground=[("readonly", BG)])
        style.configure("Horizontal.TProgressbar", troughcolor="#E9ECF0", background=BLUE)

        self.current_view = "主线执行"
        self.selected_mainline_id = self.db.current_mainline_id()
        self.selected_thought_id: int | None = None
        self.today_collapsed = {"已过期": False, "今天": False, "已完成": False}
        self.today_priority_sort = False
        self.selected_day = date.today()
        self.calendar_month = date.today().replace(day=1)
        self.calendar_selected_day = date.today()
        self._observed_local_day = date.today()
        self.layout_mode = "standard"
        self._responsive_after: str | None = None
        self._responsive_ready = False
        self.nav_buttons: dict[str, tk.Misc] = {}

        self.shell = tk.Frame(self, bg=BG)
        self.shell.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(
            self.shell, bg=SIDEBAR, width=286, highlightthickness=1, highlightbackground=BORDER
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.content = tk.Frame(self.shell, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

        self.render_sidebar()
        self.show_view("主线执行")
        self._responsive_ready = True
        self.bind("<Configure>", self._schedule_responsive_refresh, add="+")
        self.after_idle(self._initialize_responsive_layout)
        write_log("startup.log", f"Application window ready; database={db_path.resolve()}")

    def report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        write_log("crash.log", "Tkinter callback error\n" + details)
        try:
            messagebox.showerror(
                "程序发生错误",
                f"错误已记录到：\n{LOG_DIR / 'crash.log'}\n\n{exc_value}",
                parent=self,
            )
        except tk.TclError:
            pass

    def on_close(self) -> None:
        self.db.close()
        self.destroy()

    @staticmethod
    def _layout_mode_for_width(width: int) -> str:
        if width < 1320:
            return "compact"
        if width >= 1720:
            return "wide"
        return "standard"

    def _initialize_responsive_layout(self) -> None:
        mode = self._layout_mode_for_width(max(self.winfo_width(), 1180))
        if mode != self.layout_mode:
            self.layout_mode = mode
            self._apply_responsive_layout()

    def _schedule_responsive_refresh(self, event) -> None:
        if not self._responsive_ready or event.widget is not self:
            return
        if self._responsive_after:
            self.after_cancel(self._responsive_after)
        self._responsive_after = self.after(160, self._refresh_responsive_layout)

    def _refresh_responsive_layout(self) -> None:
        self._responsive_after = None
        mode = self._layout_mode_for_width(self.winfo_width())
        if mode == self.layout_mode:
            return
        self.layout_mode = mode
        self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        self.sidebar.configure(width=250 if self.layout_mode == "compact" else 286)
        self.show_view(self.current_view)

    def estimated_content_width(self) -> int:
        root_width = self.winfo_width()
        if root_width < 800:
            root_width = 1500
        sidebar_width = 250 if self.layout_mode == "compact" else 286
        return max(760, root_width - sidebar_width)

    def reading_padding(self, target_width: int = 1160, minimum: int = 34) -> int:
        return max(minimum, (self.estimated_content_width() - target_width) // 2)

    def render_sidebar(self) -> None:
        clear(self.sidebar)
        compact = self.layout_mode == "compact"
        panel = self.sidebar
        brand = tk.Frame(panel, bg=SIDEBAR, height=94)
        brand.pack(fill="x")
        brand.pack_propagate(False)
        avatar_path = APP_ROOT / "assets" / "profile-cat.png"
        try:
            self.profile_image = tk.PhotoImage(file=str(avatar_path))
            tk.Label(brand, image=self.profile_image, bg=SIDEBAR, bd=0).pack(
                side="left", padx=(20, 13), pady=19
            )
        except tk.TclError:
            tk.Label(
                brand, text="E", bg=TEXT, fg="white", width=2,
                font=(FONT_FALLBACK, 14, "bold"),
            ).pack(side="left", padx=(20, 13), pady=19, ipady=8)
        brand_copy = tk.Frame(brand, bg=SIDEBAR)
        brand_copy.pack(side="left", fill="y", pady=(25, 16))
        tk.Label(
            brand_copy, text="ENTP 自强手册", bg=SIDEBAR, fg=TEXT,
            font=(FONT, 13, "bold"), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            brand_copy, text="好奇心动力回流系统", bg=SIDEBAR, fg=MUTED,
            font=(FONT, 8), anchor="w",
        ).pack(anchor="w", pady=(3, 0))

        nav = tk.Frame(panel, bg=SIDEBAR)
        nav.pack(fill="x", padx=12, pady=(2, 0))
        nav_items = [
            ("当前主线", "主线执行", "\ue73e"),
            ("我的主线任务保管箱", "主线保管箱", "\ue838"),
            ("候审灵感", "候审灵感", "\uea80"),
        ]
        for label, name, icon in nav_items:
            selected = self.current_view == name
            nav_button = RoundedButton(
                nav,
                label,
                lambda n=name: self.show_view(n),
                bg="#EEF3FF" if selected else SIDEBAR,
                fg=BLUE if selected else TEXT,
                active_bg="#E8EEFC",
                height=48,
                radius=13,
                font=(FONT, 11, "bold" if selected else "normal"),
                anchor="w",
                padx=16,
                icon=icon,
            )
            nav_button.pack(fill="x", pady=3)
        current = next(
            (row for row in self.db.list_mainlines() if int(row["id"]) == self.db.current_mainline_id()),
            None,
        )
        if current:
            current_name = current["name"]
            if len(current_name) > (12 if compact else 16):
                current_name = current_name[: (11 if compact else 15)] + "…"
            tk.Label(
                panel, text=f"正在推进  ·  {current_name}", bg=SIDEBAR, fg=MUTED,
                font=(FONT, 9), anchor="w",
            ).pack(fill="x", padx=30, pady=(8, 16))

        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(2, 12))
        secondary_items = [
            ("今日记录", "今日记录", "\ue787"),
            ("完成日历", "历史日历", "\ue81c"),
        ]
        secondary = tk.Frame(panel, bg=SIDEBAR)
        secondary.pack(fill="x", padx=12)
        for label, name, icon in secondary_items:
            selected = self.current_view == name
            RoundedButton(
                secondary, label, lambda n=name: self.show_view(n),
                bg="#EEF3FF" if selected else SIDEBAR,
                fg=BLUE if selected else TEXT,
                active_bg="#EEF1F5", height=46, radius=12,
                font=(FONT, 11, "bold" if selected else "normal"),
                anchor="w", padx=16, icon=icon,
            ).pack(fill="x", pady=2)

        tk.Frame(panel, bg=SIDEBAR).pack(fill="both", expand=True)
        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(8, 8))
        utilities = [
            ("全部文档", self.open_markdown_folder, "\ue8a5"),
            ("设置", self.open_focus_settings_dialog, "\ue713"),
        ]
        footer = tk.Frame(panel, bg=SIDEBAR)
        footer.pack(fill="x", padx=12)
        for label, command, icon in utilities:
            RoundedButton(
                footer, label, command, bg=SIDEBAR, fg=MUTED,
                active_bg="#EEF1F5", height=42, radius=11,
                font=(FONT, 10), anchor="w", padx=16, icon=icon,
            ).pack(fill="x", pady=1)
        tk.Frame(panel, bg=SIDEBAR, height=16).pack()

    def show_view(self, name: str) -> None:
        # Refresh only the program-controlled block inside every Markdown file.
        # User notes outside that block are intentionally left untouched.
        self.markdown.sync_all(self.db)
        aliases = {
            "主线": "主线执行",
            "执行区": "主线执行",
            "当前主线": "主线执行",
            "我的主线任务保管箱": "主线保管箱",
            "候审区": "候审灵感",
            "今日清单": "今日记录",
            "完成日历": "历史日历",
        }
        name = aliases.get(name, name)
        self.current_view = name
        self.render_sidebar()
        clear(self.content)
        if name == "主线执行":
            self.render_mainline_v2()
        elif name == "主线保管箱":
            self.render_mainline_vault()
        elif name == "今日记录":
            self.render_today()
        elif name == "历史日历":
            self.render_history_calendar()
        elif name == "思路整理":
            self.render_thoughts()
        else:
            self.render_review()

    def mainline_picker(self, parent: tk.Misc, on_change: Callable | None = None) -> ttk.Combobox:
        rows = self.db.list_mainlines()
        names = [row["name"] for row in rows]
        ids = {row["name"]: row["id"] for row in rows}
        current = next((row["name"] for row in rows if row["id"] == self.selected_mainline_id), names[0])
        value = tk.StringVar(value=current)
        combo = ttk.Combobox(parent, values=names, textvariable=value, state="readonly", width=25)

        def changed(_event=None) -> None:
            self.selected_mainline_id = ids[value.get()]
            if on_change:
                on_change()
            else:
                self.show_view(self.current_view)

        combo.bind("<<ComboboxSelected>>", changed)
        return combo

    def page_header(
        self,
        title: str,
        *,
        action_text: str | None = None,
        action: Callable | None = None,
        include_picker: bool = False,
    ) -> tk.Frame:
        page_pad = self.reading_padding(target_width=1240, minimum=34)
        header = tk.Frame(self.content, bg=BG, height=112)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text=title, bg=BG, fg=TEXT, font=(FONT, 26, "bold")
        ).pack(side="left", padx=(page_pad, 26), pady=(26, 22))
        if include_picker:
            picker = self.mainline_picker(header)
            picker.pack(side="left", pady=(30, 22))
        if action_text and action:
            button(header, action_text, action, primary=True).pack(
                side="right", padx=page_pad, pady=(28, 22)
            )
        tk.Frame(header, height=1, bg=BORDER).place(relx=0, rely=1, relwidth=1, anchor="sw")
        return header

    # --------------------------- 2.0 mainline workspace ---------------------------
    def promote_mainline_from_vault(self, mainline_id: int) -> None:
        """An explicit vault action replaces the old global switch dialog."""
        self.db.set_current_mainline(mainline_id)
        self.selected_mainline_id = mainline_id
        self.calendar_selected_day = date.today()
        self.calendar_month = date.today().replace(day=1)
        self.show_view("主线执行")

    def add_task_to_vault_mainline(self, mainline_id: int) -> None:
        self.selected_mainline_id = mainline_id
        self.open_task_dialog()

    def render_mainline_vault(self) -> None:
        current_id = self.db.current_mainline_id()
        mainlines = [row for row in self.db.list_mainlines() if row["name"] != "收集箱"]
        current = next((row for row in mainlines if int(row["id"]) == current_id), None)
        stored = [row for row in mainlines if int(row["id"]) != current_id]

        scroll = ScrollFrame(self.content, bg=BG)
        scroll.pack(fill="both", expand=True)
        page = scroll.body
        pad = self.reading_padding(target_width=1040, minimum=34)

        header = tk.Frame(page, bg=BG)
        header.pack(fill="x", padx=pad, pady=(42, 26))
        title_row = tk.Frame(header, bg=BG)
        title_row.pack(fill="x")
        title_copy = tk.Frame(title_row, bg=BG)
        title_copy.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_copy, text="我的主线任务保管箱", bg=BG, fg=TEXT,
            font=(FONT, 26, "bold"), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_copy,
            text="不在执行页争夺注意力，但所有主线和任务都被好好保存。",
            bg=BG, fg=MUTED, font=(FONT, 11), anchor="w",
        ).pack(anchor="w", pady=(8, 0))
        button(
            title_row, "新建主线", self.open_mainline_dialog,
            primary=True, icon="\ue710",
        ).pack(side="right", padx=(18, 0))

        if current:
            current_surface = RoundedSurface(
                page, fill="#F5F8FF", border="#D7E4FF", radius=17, padding=1
            )
            current_surface.pack(fill="x", padx=pad, pady=(0, 30))
            body = current_surface.inner
            current_top = tk.Frame(body, bg="#F5F8FF")
            current_top.pack(fill="x", padx=22, pady=(20, 5))
            tk.Label(
                current_top, text="当前主线", bg="#E4EDFF", fg=BLUE,
                padx=9, pady=4, font=(FONT, 9, "bold"),
            ).pack(side="left")
            button(
                current_top, "返回执行", lambda: self.show_view("主线执行"),
                primary=True, icon="\ue72a",
            ).pack(side="right")
            tk.Label(
                body, text=current["name"], bg="#F5F8FF", fg=TEXT,
                font=(FONT, 18, "bold"), anchor="w",
            ).pack(fill="x", padx=22, pady=(7, 4))
            stats = self.db.mainline_stats(current_id)
            done = int(stats["done"] or 0)
            total = int(stats["total"] or 0)
            tk.Label(
                body,
                text=f"{total - done} 个待推进任务  ·  {done} 个已完成",
                bg="#F5F8FF", fg=MUTED, font=(FONT, 10), anchor="w",
            ).pack(fill="x", padx=22, pady=(0, 20))

        section = tk.Frame(page, bg=BG)
        section.pack(fill="x", padx=pad, pady=(0, 12))
        tk.Label(
            section, text="保管中的主线", bg=BG, fg=TEXT,
            font=(FONT, 15, "bold"),
        ).pack(side="left")
        tk.Label(
            section, text=str(len(stored)), bg=BG, fg=MUTED,
            font=(FONT, 11),
        ).pack(side="left", padx=(8, 0))

        if not stored:
            empty = RoundedSurface(page, fill="#FAFBFC", border=BORDER, radius=16, padding=1)
            empty.pack(fill="x", padx=pad)
            tk.Label(
                empty.inner, text="保管箱是空的", bg="#FAFBFC", fg=TEXT,
                font=(FONT, 14, "bold"),
            ).pack(anchor="w", padx=22, pady=(22, 5))
            tk.Label(
                empty.inner, text="新建的主线会先保存在这里，不会打断当前执行。",
                bg="#FAFBFC", fg=MUTED, font=(FONT, 10),
            ).pack(anchor="w", padx=22, pady=(0, 22))
        else:
            for mainline in stored:
                self.render_vault_mainline(page, mainline, pad)
        tk.Frame(page, bg=BG, height=34).pack()

    def render_vault_mainline(self, parent: tk.Misc, mainline, pad: int) -> None:
        mainline_id = int(mainline["id"])
        tasks = self.db.list_tasks(mainline_id)
        active = [task for task in tasks if task["status"] != "完成"]
        done = len(tasks) - len(active)
        surface = RoundedSurface(parent, fill=BG, border=BORDER, radius=16, padding=1)
        surface.pack(fill="x", padx=pad, pady=(0, 12))
        body = surface.inner
        top = tk.Frame(body, bg=BG)
        top.pack(fill="x", padx=22, pady=(18, 5))
        tk.Label(
            top, text=mainline["name"], bg=BG, fg=TEXT,
            font=(FONT, 15, "bold"), anchor="w",
        ).pack(side="left", fill="x", expand=True)
        button(
            top, "设为当前主线",
            lambda mid=mainline_id: self.promote_mainline_from_vault(mid),
            subtle=True, icon="\ue72a",
        ).pack(side="right")
        if mainline["vision"]:
            tk.Label(
                body, text=mainline["vision"], bg=BG, fg=MUTED,
                font=(FONT, 10), anchor="w", justify="left", wraplength=760,
            ).pack(fill="x", padx=22, pady=(1, 7))
        tk.Label(
            body, text=f"{len(active)} 个待推进  ·  {done} 个已完成",
            bg=BG, fg=MUTED, font=(FONT, 9), anchor="w",
        ).pack(fill="x", padx=22, pady=(0, 11))
        if active:
            tk.Frame(body, bg=BORDER, height=1).pack(fill="x", padx=22)
            for task in active[:3]:
                row = tk.Frame(body, bg=BG, height=43)
                row.pack(fill="x", padx=22)
                row.pack_propagate(False)
                tk.Label(
                    row, text="□", bg=BG, fg=MUTED, font=(FONT_FALLBACK, 13),
                ).pack(side="left", padx=(0, 8))
                tk.Button(
                    row, text=task["title"],
                    command=lambda tid=int(task["id"]): self.open_task_detail(tid),
                    bg=BG, fg=TEXT, activebackground=BLUE_SOFT, activeforeground=BLUE,
                    relief="flat", bd=0, cursor="hand2", anchor="w",
                    font=(FONT, 10),
                ).pack(side="left", fill="x", expand=True)
                tk.Label(
                    row, text=task["status"], bg=BG, fg=MUTED,
                    font=(FONT, 9),
                ).pack(side="right")
                tk.Frame(body, bg="#EFF0F2", height=1).pack(fill="x", padx=22)
        footer = tk.Frame(body, bg=BG)
        footer.pack(fill="x", padx=18, pady=(8, 14))
        tk.Button(
            footer, text="＋ 添加任务",
            command=lambda mid=mainline_id: self.add_task_to_vault_mainline(mid),
            bg=BG, fg=BLUE, activebackground=BLUE_SOFT, activeforeground=BLUE,
            relief="flat", bd=0, cursor="hand2", padx=5, pady=5,
            font=(FONT, 10),
        ).pack(side="left")
        tk.Button(
            footer, text="打开笔记",
            command=lambda mid=mainline_id: self.open_markdown_editor("mainline", mid),
            bg=BG, fg=MUTED, activebackground="#F2F3F5", activeforeground=TEXT,
            relief="flat", bd=0, cursor="hand2", padx=8, pady=5,
            font=(FONT, 9),
        ).pack(side="right")

    def render_mainline_v2(self) -> None:
        current_id = self.db.current_mainline_id()
        self.selected_mainline_id = current_id
        mainline = next(
            row for row in self.db.list_mainlines() if int(row["id"]) == current_id
        )
        scroll = ScrollFrame(self.content, bg=BG)
        scroll.pack(fill="both", expand=True)
        page = scroll.body
        pad = 28 if self.layout_mode == "compact" else 36

        header = tk.Frame(page, bg=BG)
        header.pack(fill="x", padx=pad, pady=(34, 0))
        tk.Label(
            header, text="当前主线", bg="#EAF1FF", fg=BLUE,
            padx=10, pady=4, font=(FONT, 9, "bold"),
        ).pack(anchor="w")
        title_row = tk.Frame(header, bg=BG)
        title_row.pack(fill="x", pady=(10, 0))
        tk.Label(
            title_row, text=mainline["name"], bg=BG, fg=TEXT,
            font=(FONT, 25, "bold"), anchor="w",
        ).pack(side="left", fill="x", expand=True)
        button(
            title_row, "编辑主线", self.open_edit_mainline_dialog,
            subtle=True, icon="\ue70f",
        ).pack(side="right", padx=(8, 0))
        button(
            title_row, "主线笔记",
            lambda: self.open_markdown_editor("mainline", current_id),
            subtle=True, icon="\ue8a5",
        ).pack(side="right")
        if mainline["vision"]:
            tk.Label(
                header, text=mainline["vision"], bg=BG, fg=MUTED,
                font=(FONT, 11), anchor="w", justify="left", wraplength=880,
            ).pack(fill="x", pady=(9, 0))
        weekdays = "一二三四五六日"
        settings_row = tk.Frame(header, bg=BG)
        settings_row.pack(fill="x", pady=(15, 18))
        date_text = (
            f"{date.today().year}年{date.today().month}月{date.today().day}日"
            f" · 周{weekdays[date.today().weekday()]}"
        )
        focus_text = f"节奏：{mainline['focus_until'] or '自由推进'}"
        review_text = f"复盘：{mainline['review_mode'] or '按需'}"
        tk.Label(
            settings_row, text=f"{date_text}    ·    {focus_text}    ·    {review_text}",
            bg=BG, fg=MUTED, font=(FONT, 10),
        ).pack(side="left")
        tk.Button(
            settings_row, text="调整", command=self.open_focus_settings_dialog,
            bg=BG, fg=BLUE, activebackground=BLUE_SOFT, activeforeground=BLUE,
            relief="flat", bd=0, cursor="hand2", padx=12, font=(FONT, 10),
        ).pack(side="left")
        tk.Frame(header, bg=BORDER, height=1).pack(fill="x", pady=(0, 18))

        columns = tk.Frame(page, bg=BG)
        columns.pack(fill="both", expand=True, padx=pad, pady=(0, 30))
        compact = self.layout_mode == "compact"
        if compact:
            columns.grid_columnconfigure(0, weight=1)
            columns.grid_columnconfigure(1, weight=0)
        else:
            columns.grid_columnconfigure(0, weight=1, minsize=540)
            columns.grid_columnconfigure(1, weight=0, minsize=420)
        columns.grid_rowconfigure(1 if compact else 0, weight=1)

        left = tk.Frame(columns, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 0 if compact else 12))
        right = tk.Frame(columns, bg=BG)
        right.grid(
            row=1 if compact else 0,
            column=0 if compact else 1,
            sticky="nsew",
            pady=(14, 0) if compact else 0,
        )

        self.render_focus_panel(left, current_id)
        self.render_mainline_task_list(left, current_id)
        self.render_completion_calendar(right, current_id)

    def render_focus_panel(self, parent: tk.Misc, mainline_id: int) -> None:
        focus_task = self.db.get_focus_task(mainline_id)
        surface = RoundedSurface(parent, fill=BG, border=BORDER, radius=13, padding=1)
        surface.pack(fill="x", pady=(0, 12))
        body = surface.inner
        tk.Label(
            body, text="现在推进", bg=BG, fg=TEXT, font=(FONT, 13, "bold")
        ).pack(anchor="w", padx=20, pady=(18, 10))
        if not focus_task:
            tk.Label(
                body, text="这条主线还没有可推进的任务", bg=BG, fg=MUTED,
                font=(FONT, 12),
            ).pack(anchor="w", padx=20, pady=(2, 12))
            button(body, "＋ 添加任务", self.open_task_dialog, primary=True).pack(
                anchor="w", padx=18, pady=(0, 16)
            )
            return

        title_row = tk.Frame(body, bg=BG)
        title_row.pack(fill="x", padx=18)
        tk.Label(
            title_row, text=focus_task["title"], bg=BG, fg=TEXT,
            font=(FONT, 16, "bold"), anchor="w",
        ).pack(side="left")
        button(
            title_row, "任务笔记",
            lambda tid=int(focus_task["id"]): self.open_markdown_editor("task", tid),
            subtle=True, icon="\ue8a5",
        ).pack(side="right")
        tk.Label(
            body, text="下一步", bg=BG, fg=TEXT, font=(FONT, 11),
        ).pack(anchor="w", padx=20, pady=(15, 7))
        action_var = tk.StringVar(
            value=focus_task["next_action"] or focus_task["description"] or "写下下一次可以真正动手的动作"
        )
        action = entry(body, action_var)
        action.pack(fill="x", padx=20)

        def save_next_action(_event=None) -> None:
            value = action_var.get().strip()
            if value and value != "写下下一次可以真正动手的动作":
                self.db.update_task(int(focus_task["id"]), next_action=value)

        action.bind("<Return>", save_next_action)
        action.bind("<FocusOut>", save_next_action)
        actions = tk.Frame(body, bg=BG)
        actions.pack(fill="x", padx=20, pady=(16, 20))
        button(
            actions, "记录这次执行",
            lambda tid=int(focus_task["id"]): self.open_task_execution_dialog(tid),
            primary=True,
            icon="\ue70f",
        ).pack(side="left")
        button(
            actions, "我卡住了",
            lambda tid=int(focus_task["id"]): self.open_stuck_dialog(tid),
            icon="\ue90a",
        ).pack(side="left", padx=8)
        button(actions, "暂存新灵感", self.open_thought_dialog, icon="\uea80").pack(side="left")

    def render_mainline_task_list(self, parent: tk.Misc, mainline_id: int) -> None:
        surface = RoundedSurface(parent, fill=BG, border=BORDER, radius=13, padding=1)
        surface.pack(fill="both", expand=True)
        body = surface.inner
        heading = tk.Frame(body, bg=BG)
        heading.pack(fill="x", padx=18, pady=(15, 7))
        tk.Label(
            heading, text="主线任务", bg=BG, fg=TEXT, font=(FONT, 13, "bold")
        ).pack(side="left")
        tk.Button(
            heading, text="＋ 添加任务", command=self.open_task_dialog,
            bg=BG, fg=BLUE, activebackground=BLUE_SOFT, activeforeground=BLUE,
            relief="flat", bd=0, cursor="hand2", font=(FONT, 11),
        ).pack(side="right")

        all_tasks = self.db.list_tasks(mainline_id)
        active = [task for task in all_tasks if task["status"] != "完成"]
        completed = [task for task in all_tasks if task["status"] == "完成"]
        active.sort(key=lambda row: (not bool(row["is_focus"]), not bool(row["is_today"]), int(row["id"])))
        tk.Label(
            body, text=f"进行中  {len(active)}", bg=BG, fg=TEXT,
            font=(FONT, 10, "bold"), anchor="w",
        ).pack(fill="x", padx=18, pady=(5, 2))
        if active:
            for task in active[:7]:
                self.render_mainline_task_row(body, task, completed=False)
        else:
            tk.Label(
                body, text="没有进行中的任务", bg=BG, fg=MUTED,
                font=(FONT, 9), anchor="w",
            ).pack(fill="x", padx=18, pady=10)

        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", padx=18, pady=(8, 8))
        tk.Label(
            body, text=f"已完成  {len(completed)}", bg=BG, fg=TEXT,
            font=(FONT, 10, "bold"), anchor="w",
        ).pack(fill="x", padx=18, pady=(0, 2))
        for task in completed[:5]:
            self.render_mainline_task_row(body, task, completed=True)
        tk.Frame(body, bg=BG, height=12).pack()

    def render_mainline_task_row(self, parent: tk.Misc, task, *, completed: bool) -> None:
        row = tk.Frame(parent, bg=BG, height=48)
        row.pack(fill="x", padx=18)
        row.pack_propagate(False)
        checked = tk.BooleanVar(value=completed)
        tk.Checkbutton(
            row,
            variable=checked,
            command=lambda tid=int(task["id"]), value=not completed: self.complete_task_v2(tid, value),
            bg=BG,
            activebackground=BG,
            selectcolor=GREEN if completed else BG,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        ).pack(side="left")
        if task["is_focus"] and not completed:
            tk.Label(
                row, text="当前推进", bg=BLUE_SOFT, fg=BLUE,
                padx=7, pady=3, font=(FONT, 9, "bold"),
            ).pack(side="left", padx=(2, 7))
        title = tk.Button(
            row,
            text=task["title"],
            command=lambda tid=int(task["id"]): self.select_focus_task(tid),
            anchor="w",
            bg=BG,
            fg="#8A8F98" if completed else TEXT,
            activebackground=BLUE_SOFT,
            activeforeground=BLUE,
            relief="flat",
            bd=0,
            cursor="hand2",
            font=(FONT, 11),
        )
        title.pack(side="left", fill="x", expand=True)
        if completed:
            tk.Label(
                row, text=self.task_completion_text(int(task["id"]), task["completed_at"]),
                bg=BG, fg="#9A9EA5", font=(FONT, 9),
            ).pack(side="right", padx=(8, 0))
        else:
            tk.Button(
                row, text="笔记",
                command=lambda tid=int(task["id"]): self.open_markdown_editor("task", tid),
                bg=BG, fg=MUTED, activebackground=BLUE_SOFT, activeforeground=BLUE,
                relief="flat", bd=0, cursor="hand2", font=(FONT, 9), padx=6,
            ).pack(side="right")
        tk.Frame(parent, bg="#ECEEF1", height=1).pack(fill="x", padx=18)

    def task_completion_text(self, task_id: int, completed_at: str) -> str:
        raw = completed_at or ""
        if not raw:
            latest = self.db.row(
                """SELECT entry_date, completed_at FROM daily_entries
                   WHERE task_id = ? AND state = 'completed'
                   ORDER BY entry_date DESC, id DESC LIMIT 1""",
                (task_id,),
            )
            if latest:
                raw = latest["completed_at"] or latest["entry_date"]
        try:
            stamp = datetime.fromisoformat(raw)
            if stamp.date() == date.today():
                return f"完成于 今天 {stamp.strftime('%H:%M')}"
            return f"完成于 {stamp.month}月{stamp.day}日 {stamp.strftime('%H:%M')}"
        except (TypeError, ValueError):
            try:
                day_value = date.fromisoformat(raw)
                return f"完成于 {day_value.month}月{day_value.day}日"
            except (TypeError, ValueError):
                return "旧版完成记录"

    def complete_task_v2(self, task_id: int, completed: bool) -> None:
        self.db.set_task_completed(task_id, completed)
        self.calendar_selected_day = date.today()
        self.calendar_month = date.today().replace(day=1)
        self.show_view("主线执行")

    def select_focus_task(self, task_id: int) -> None:
        task = self.db.get_task(task_id)
        if not task:
            return
        if task["status"] == "完成":
            self.open_task_detail(task_id)
            return
        self.db.set_focus_task(task_id)
        self.show_view("主线执行")

    def shift_completion_month(self, delta: int) -> None:
        index = self.calendar_month.year * 12 + self.calendar_month.month - 1 + delta
        year, month_zero = divmod(index, 12)
        candidate = date(year, month_zero + 1, 1)
        if candidate <= date.today().replace(day=1):
            self.calendar_month = candidate
            self.calendar_selected_day = candidate
            self.show_view(self.current_view)

    def select_completion_day(self, value: date) -> None:
        if value > date.today():
            return
        self.calendar_selected_day = value
        self.calendar_month = value.replace(day=1)
        self.show_view(self.current_view)

    def render_completion_calendar(self, parent: tk.Misc, mainline_id: int) -> None:
        surface = RoundedSurface(parent, fill=BG, border=BORDER, radius=13, padding=1)
        surface.pack(fill="both", expand=True)
        body = surface.inner
        tk.Label(
            body, text="完成日历", bg=BG, fg=TEXT, font=(FONT, 13, "bold")
        ).pack(anchor="w", padx=20, pady=(18, 10))
        month_row = tk.Frame(body, bg=BG)
        month_row.pack(fill="x", padx=14)
        tk.Button(
            month_row, text="‹", command=lambda: self.shift_completion_month(-1),
            bg=BG, fg=MUTED, activebackground=GRAY_SOFT, relief="flat", bd=0,
            cursor="hand2", font=(FONT_FALLBACK, 17),
        ).pack(side="left")
        tk.Label(
            month_row,
            text=f"{self.calendar_month.year}年{self.calendar_month.month}月",
            bg=BG, fg=TEXT, font=(FONT, 11),
        ).pack(side="left", expand=True)
        tk.Button(
            month_row, text="›", command=lambda: self.shift_completion_month(1),
            state="normal" if self.calendar_month < date.today().replace(day=1) else "disabled",
            bg=BG, fg=MUTED, disabledforeground="#D5D7DB", activebackground=GRAY_SOFT,
            relief="flat", bd=0, cursor="hand2", font=(FONT_FALLBACK, 17),
        ).pack(side="right")

        calendar_frame = tk.Frame(body, bg=BG)
        calendar_frame.pack(fill="x", padx=14, pady=(8, 4))
        for col, label in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            calendar_frame.grid_columnconfigure(col, weight=1, uniform="calendar")
            tk.Label(
                calendar_frame, text=label, bg=BG, fg=MUTED, font=(FONT, 10)
            ).grid(row=0, column=col, sticky="ew", pady=(0, 6))
        completion_days = self.db.completion_days(
            self.calendar_month.year, self.calendar_month.month, mainline_id
        )
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(
            self.calendar_month.year, self.calendar_month.month
        )
        for row_index, week in enumerate(weeks, start=1):
            for col, value in enumerate(week):
                in_month = value.month == self.calendar_month.month
                count = completion_days.get(value.isoformat(), 0)
                selected = value == self.calendar_selected_day
                label = str(value.day)
                if count:
                    label += "\n•"
                day_button = tk.Button(
                    calendar_frame,
                    text=label,
                    command=lambda day_value=value: self.select_completion_day(day_value),
                    state="normal" if in_month and value <= date.today() else "disabled",
                    bg=BLUE_SOFT if selected else BG,
                    fg=BLUE if count or selected else TEXT,
                    disabledforeground="#B5BAC3" if not in_month else "#D5D7DB",
                    activebackground=BLUE_SOFT,
                    activeforeground=BLUE,
                    relief="flat",
                    bd=0,
                    highlightthickness=1 if selected else 0,
                    highlightbackground=BLUE,
                    cursor="hand2" if in_month and value <= date.today() else "arrow",
                    font=(FONT, 10, "bold" if selected else "normal"),
                    height=2,
                )
                day_button.grid(row=row_index, column=col, sticky="nsew", padx=1, pady=1)

        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", padx=18, pady=(10, 12))
        completed = self.db.completed_entries_on(
            self.calendar_selected_day.isoformat(), mainline_id
        )
        tk.Label(
            body,
            text=f"{self.calendar_selected_day.month}月{self.calendar_selected_day.day}日完成 {len(completed)} 项",
            bg=BG, fg=TEXT, font=(FONT, 12, "bold"),
        ).pack(anchor="w", padx=18)
        if completed:
            for item in completed[:5]:
                completion_row = tk.Frame(body, bg="#FAFBFC", height=42)
                completion_row.pack(fill="x", padx=18, pady=(7, 0))
                completion_row.pack_propagate(False)
                tk.Label(
                    completion_row, text="完成", bg=GREEN_SOFT, fg=GREEN,
                    padx=7, pady=3, font=(FONT, 9, "bold"),
                ).pack(side="left", padx=(8, 7))
                tk.Label(
                    completion_row, text=item["title"], bg="#FAFBFC", fg=TEXT,
                    font=(FONT, 10), anchor="w",
                ).pack(side="left", fill="x", expand=True)
                time_text = ""
                try:
                    time_text = datetime.fromisoformat(item["completed_at"]).strftime("%H:%M")
                except (TypeError, ValueError):
                    pass
                tk.Label(
                    completion_row, text=time_text, bg="#FAFBFC", fg=MUTED,
                    font=(FONT, 9),
                ).pack(side="right", padx=8)
        else:
            tk.Label(
                body, text="这一天还没有完成记录", bg=BG, fg=MUTED,
                font=(FONT, 10),
            ).pack(anchor="w", padx=18, pady=(8, 0))
        tk.Label(
            body, text="完成任务后，系统会自动记录到这一天。",
            bg=BG, fg=MUTED, font=(FONT, 9), wraplength=330, justify="left",
        ).pack(anchor="w", padx=18, pady=(15, 5))
        tk.Button(
            body, text="查看当天记录", command=self.open_selected_calendar_day,
            bg=BG, fg=BLUE, activebackground=BLUE_SOFT, activeforeground=BLUE,
            relief="flat", bd=0, cursor="hand2", font=(FONT, 10),
        ).pack(anchor="w", padx=14, pady=(0, 15))

    def open_selected_calendar_day(self) -> None:
        self.selected_day = self.calendar_selected_day
        self.show_view("今日记录")

    def render_history_calendar(self) -> None:
        current_id = self.db.current_mainline_id()
        self.selected_mainline_id = current_id
        header = self.page_header("历史日历")
        tk.Label(
            header, text="日历只保存发生过的事实，不计算连续天数。",
            bg=BG, fg=MUTED, font=(FONT, 9),
        ).pack(side="left", pady=(30, 22))
        wrap = tk.Frame(self.content, bg=BG)
        wrap.pack(fill="both", expand=True, padx=self.reading_padding(960, 30), pady=24)
        self.render_completion_calendar(wrap, current_id)

    def open_edit_mainline_dialog(self) -> None:
        mainline_id = self.db.current_mainline_id()
        mainline = next(
            row for row in self.db.list_mainlines() if int(row["id"]) == mainline_id
        )
        win, body = self.dialog("编辑主线", "560x430")
        name_var = tk.StringVar(value=mainline["name"])
        self.form_label(body, "主线名称")
        name = entry(body, name_var)
        name.pack(fill="x")
        self.form_label(body, "为什么现在想推进它（可选）")
        vision = text_box(body, mainline["vision"], 5)
        vision.pack(fill="x")

        def save() -> None:
            if not name_var.get().strip():
                messagebox.showwarning("缺少名称", "请填写主线名称。", parent=win)
                return
            self.db.update_mainline(
                mainline_id, name=name_var.get(), vision=vision.get("1.0", "end")
            )
            win.destroy()
            self.show_view("主线执行")

        button(body, "保存", save, primary=True).pack(anchor="e", pady=18)

    def open_focus_settings_dialog(self) -> None:
        mainline_id = self.db.current_mainline_id()
        mainline = next(
            row for row in self.db.list_mainlines() if int(row["id"]) == mainline_id
        )
        win, body = self.dialog("专注设置", "560x480")
        tk.Label(
            body,
            text="时间限制和复盘提醒都是可选项。留空时，系统不会倒计时或催促。",
            bg=BG, fg=MUTED, font=(FONT, 9), wraplength=470, justify="left",
        ).pack(anchor="w", pady=(0, 12))
        focus_var = tk.StringVar(value=mainline["focus_until"])
        review_var = tk.StringVar(value=mainline["review_mode"] or "按需复盘")
        next_review_var = tk.StringVar(value=mainline["next_review_date"])
        self.form_label(body, "可选结束日期（YYYY-MM-DD）")
        focus_entry = entry(body, focus_var)
        focus_entry.pack(fill="x")
        self.form_label(body, "复盘方式")
        ttk.Combobox(
            body,
            values=("按需复盘", "每周提醒", "每月提醒", "指定日期"),
            textvariable=review_var,
            state="readonly",
        ).pack(fill="x")
        self.form_label(body, "下次复盘日期（可选）")
        next_entry = entry(body, next_review_var)
        next_entry.pack(fill="x")

        def validate_optional_day(value: str) -> bool:
            if not value.strip():
                return True
            try:
                date.fromisoformat(value.strip())
                return True
            except ValueError:
                return False

        def save() -> None:
            if not validate_optional_day(focus_var.get()) or not validate_optional_day(next_review_var.get()):
                messagebox.showwarning("日期格式不正确", "日期请使用 YYYY-MM-DD，或保持为空。", parent=win)
                return
            self.db.update_mainline(
                mainline_id,
                focus_until=focus_var.get(),
                review_mode=review_var.get(),
                next_review_date=next_review_var.get(),
            )
            win.destroy()
            self.show_view("主线执行")

        button(body, "保存设置", save, primary=True).pack(anchor="e", pady=20)

    def open_task_execution_dialog(self, task_id: int) -> None:
        task = self.db.get_task(task_id)
        if not task:
            return
        win, body = self.dialog("记录这次执行", "620x640")
        tk.Label(
            body, text=task["title"], bg=BG, fg=TEXT,
            font=(FONT, 12, "bold"), anchor="w",
        ).pack(fill="x", pady=(0, 10))
        self.form_label(body, "实际做了什么")
        action = text_box(body, task["next_action"] or task["description"], 4)
        action.pack(fill="x")
        self.form_label(body, "产生了什么结果或新发现（可选）")
        result = text_box(body, "", 4)
        result.pack(fill="x")
        self.form_label(body, "下一步（可选）")
        next_action = text_box(body, "", 3)
        next_action.pack(fill="x")
        complete_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            body, text="这次执行已经完成整个任务", variable=complete_var,
            bg=BG, fg=TEXT, activebackground=BG, font=(FONT, 9),
        ).pack(anchor="w", pady=14)

        def save() -> None:
            action_value = action.get("1.0", "end").strip()
            if not action_value:
                messagebox.showwarning("缺少行动", "请记录这次实际做了什么。", parent=win)
                return
            self.db.add_task_execution_log(
                task_id,
                action=action_value,
                result=result.get("1.0", "end"),
                next_action=next_action.get("1.0", "end"),
                complete=complete_var.get(),
            )
            win.destroy()
            self.calendar_selected_day = date.today()
            self.calendar_month = date.today().replace(day=1)
            self.show_view("主线执行")

        button(body, "保存执行记录", save, primary=True).pack(anchor="e", pady=8)

    def open_stuck_dialog(self, task_id: int) -> None:
        task = self.db.get_task(task_id)
        if not task:
            return
        win, body = self.dialog("我卡住了", "660x620")
        tk.Label(
            body, text="先把卡点写清楚，再从候审灵感里带回少量燃料。",
            bg=BG, fg=MUTED, font=(FONT, 9),
        ).pack(anchor="w", pady=(0, 10))
        self.form_label(body, "现在卡在哪里")
        blocker = text_box(body, "", 4)
        blocker.pack(fill="x")
        self.form_label(body, "可以先把动作缩小成")
        smaller_var = tk.StringVar(value=task["next_action"] or task["description"])
        smaller = entry(body, smaller_var)
        smaller.pack(fill="x")
        tk.Label(
            body, text="候审灵感中与这条主线最近的内容", bg=BG, fg=TEXT,
            font=(FONT, 9, "bold"),
        ).pack(anchor="w", pady=(16, 7))
        thoughts = self.db.list_thoughts(task["mainline_id"], statuses=("待整理", "已成型", "验证中"))[:3]
        if thoughts:
            for thought in thoughts:
                row = tk.Frame(body, bg="#FAFBFC", height=44)
                row.pack(fill="x", pady=3)
                row.pack_propagate(False)
                tk.Label(
                    row, text=thought["title"], bg="#FAFBFC", fg=TEXT,
                    font=(FONT, 9), anchor="w",
                ).pack(side="left", fill="x", expand=True, padx=10)
                button(
                    row, "查看",
                    lambda tid=int(thought["id"]), window=win: self.open_recalled_thought(tid, window),
                    subtle=True,
                ).pack(side="right", padx=8, pady=3)
        else:
            tk.Label(
                body, text="候审区还没有可召回的灵感。", bg=BG, fg=MUTED,
                font=(FONT, 9),
            ).pack(anchor="w", pady=8)

        def save_smaller() -> None:
            if smaller_var.get().strip():
                self.db.update_task(task_id, next_action=smaller_var.get())
            win.destroy()
            self.show_view("主线执行")

        button(body, "保存更小的下一步", save_smaller, primary=True).pack(anchor="e", pady=16)

    def open_recalled_thought(self, thought_id: int, win: tk.Toplevel) -> None:
        win.destroy()
        self.selected_thought_id = thought_id
        self.show_view("思路整理")

    # --------------------------- Mainline board ---------------------------
    def render_board(self) -> None:
        mainline = next(
            row for row in self.db.list_mainlines() if row["id"] == self.selected_mainline_id
        )
        header = self.page_header(
            mainline["name"], action_text="＋ 新任务", action=self.open_task_dialog
        )
        picker = self.mainline_picker(header)
        picker.pack(side="right", padx=(0, 12), pady=(28, 22))
        button(
            header,
            "MD 主线文档",
            lambda: self.open_markdown_editor("mainline", self.selected_mainline_id),
        ).pack(side="right", padx=(0, 10), pady=(28, 22))
        button(header, "＋ 主线", self.open_mainline_dialog).pack(
            side="right", padx=(0, 10), pady=(28, 22)
        )

        summary = tk.Frame(self.content, bg=BG, height=74)
        summary.pack(fill="x")
        summary.pack_propagate(False)
        stats = self.db.mainline_stats(self.selected_mainline_id)
        total = stats["total"] or 0
        done = stats["done"] or 0
        pct = int(done / total * 100) if total else 0
        tk.Label(summary, text="进度总览", bg=BG, fg=TEXT, font=(FONT, 10, "bold")).pack(
            side="left", padx=(40, 24)
        )
        tk.Label(
            summary, text=f"{done} / {total} 已完成   {pct}%", bg=BG, fg=MUTED, font=(FONT, 10)
        ).pack(side="left")
        progress = ttk.Progressbar(summary, length=150, maximum=100, value=pct)
        progress.pack(side="left", padx=18)
        tk.Label(
            summary, text=mainline["vision"], bg=BG, fg=MUTED, font=(FONT, 9)
        ).pack(side="left", padx=6)

        compact = self.layout_mode == "compact"
        column_count = 2 if compact else 4
        board_pad = self.reading_padding(target_width=1420, minimum=24)
        board = tk.Frame(self.content, bg=BG)
        board.pack(fill="both", expand=True, padx=board_pad, pady=(0, 28))
        for index, status in enumerate(TASK_STATUSES):
            grid_column = index % column_count
            grid_row = index // column_count
            board.grid_columnconfigure(grid_column, weight=1, uniform="board")
            board.grid_rowconfigure(grid_row, weight=1, uniform="board_rows")
            color, soft = self.task_colors(status)
            column_surface = RoundedSurface(
                board, fill=soft, border="#ECEEF1", radius=16, padding=1
            )
            column_surface.grid(
                row=grid_row,
                column=grid_column,
                sticky="nsew",
                padx=7,
                pady=7 if compact else 0,
            )
            column = column_surface.inner
            tasks = self.db.list_tasks(self.selected_mainline_id, status=status)
            column_header = tk.Frame(column, bg=soft, height=52)
            column_header.pack(fill="x")
            column_header.pack_propagate(False)
            tk.Label(
                column_header, text="●", bg=soft, fg=color, font=(FONT, 9)
            ).pack(side="left", padx=(16, 7))
            tk.Label(
                column_header,
                text=f"{status}  {len(tasks)}",
                bg=soft,
                fg=TEXT,
                font=(FONT, 11, "bold"),
            ).pack(side="left")
            button(
                column_header,
                "＋",
                lambda s=status: self.open_task_dialog(default_status=s),
                subtle=True,
                width=2,
            ).pack(side="right", padx=8, pady=8)
            scroll = ScrollFrame(column, bg=soft)
            scroll.pack(fill="both", expand=True, padx=9, pady=(0, 9))
            for task in tasks:
                self.render_task_card(scroll.body, task, status)

    @staticmethod
    def task_colors(status: str) -> tuple[str, str]:
        return {
            "待执行": ("#8B9099", "#FAFAFA"),
            "今日": (YELLOW, YELLOW_SOFT),
            "执行中": (GREEN, GREEN_SOFT),
            "完成": (ROSE, ROSE_SOFT),
        }.get(status, (MUTED, GRAY_SOFT))

    def render_task_card(self, parent: tk.Misc, task, status: str) -> None:
        card = RoundedSurface(
            parent, fill=BG, border="#DFE2E6", radius=12, shadow=True, cursor="hand2"
        )
        card.pack(fill="x", padx=3, pady=7)
        content = card.inner
        tk.Label(
            content,
            text=task["title"],
            anchor="w",
            justify="left",
            wraplength=max(
                220,
                int(self.estimated_content_width() / (2 if self.layout_mode == "compact" else 4)) - 100,
            ),
            bg=BG,
            fg=TEXT,
            font=(FONT, 12, "bold"),
        ).pack(fill="x", padx=14, pady=(13, 8))
        meta = tk.Frame(content, bg=BG)
        meta.pack(fill="x", padx=12, pady=(0, 8))
        pill_bg = ROSE_SOFT if task["priority"] == "重要" else GRAY_SOFT
        pill_fg = ROSE if task["priority"] == "重要" else MUTED
        tk.Label(
            meta,
            text=task["priority"],
            bg=pill_bg,
            fg=pill_fg,
            padx=7,
            pady=3,
            font=(FONT, 10),
        ).pack(side="left")
        if task["due_date"]:
            tk.Label(
                meta, text=task["due_date"][5:], bg=BG, fg=MUTED, font=(FONT, 10)
            ).pack(side="right")
        actions = tk.Frame(content, bg=BG)
        actions.pack(fill="x", padx=8, pady=(0, 9))
        idx = TASK_STATUSES.index(status)
        if idx > 0:
            button(
                actions,
                "←",
                lambda tid=task["id"], s=TASK_STATUSES[idx - 1]: self.move_task(tid, s),
                subtle=True,
                width=2,
            ).pack(side="left", padx=2)
        if idx < len(TASK_STATUSES) - 1:
            button(
                actions,
                "推进 →",
                lambda tid=task["id"], s=TASK_STATUSES[idx + 1]: self.move_task(tid, s),
                subtle=True,
            ).pack(side="right", padx=2)
        button(
            actions,
            "MD",
            lambda tid=task["id"]: self.open_markdown_editor("task", tid),
            subtle=True,
            width=3,
        ).pack(side="left", padx=2)
        bind_click(
            card,
            lambda _e, tid=task["id"]: self.open_task_detail(tid),
        )
        for action in actions.winfo_children():
            # Replace the inherited card-click binding without blocking the
            # Button class binding that invokes the command on release.
            action.bind("<Button-1>", lambda _e: None)

    def move_task(self, task_id: int, status: str) -> None:
        self.db.update_task_status(task_id, status)
        self.show_view(self.current_view)

    # --------------------------- Today / execution ---------------------------
    def render_today(self) -> None:
        # A window can stay open across midnight. Re-anchor to the new day only
        # when the user was looking at the previous real "today".
        real_today = date.today()
        if real_today != self._observed_local_day:
            self.db.refresh_today_flags()
            if self.selected_day == self._observed_local_day:
                self.selected_day = real_today
            self._observed_local_day = real_today
        selected_iso = self.selected_day.isoformat()
        is_real_today = self.selected_day == real_today
        page_pad = self.reading_padding(target_width=1160, minimum=34)

        header = tk.Frame(self.content, bg=BG, height=94)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text="☷",
            bg=BG,
            fg=MUTED,
            font=(FONT, 20),
        ).pack(side="left", padx=(page_pad, 10), pady=(24, 18))
        tk.Label(
            header,
            text=self.format_day_heading(self.selected_day),
            bg=BG,
            fg=TEXT,
            font=(FONT, 25, "bold"),
        ).pack(side="left", pady=(22, 18))
        more = tk.Button(
            header,
            text="•••",
            command=lambda: self.open_today_menu(more),
            bg=BG,
            fg=MUTED,
            activebackground=GRAY_SOFT,
            activeforeground=TEXT,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=12,
            pady=7,
            font=(FONT_FALLBACK, 13, "bold"),
        )
        more.pack(side="right", padx=(4, 34), pady=(24, 18))
        tk.Button(
            header,
            text="▦",
            command=self.open_calendar_dialog,
            bg=BG,
            fg=MUTED,
            activebackground=BLUE_SOFT,
            activeforeground=BLUE,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=11,
            pady=7,
            font=(FONT, 14),
        ).pack(side="right", pady=(24, 18))
        tk.Button(
            header,
            text="›",
            command=lambda: self.shift_selected_day(1),
            state="normal" if self.selected_day < real_today else "disabled",
            bg=BG,
            fg=MUTED,
            disabledforeground="#D5D7DB",
            activebackground=GRAY_SOFT,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=7,
            font=(FONT_FALLBACK, 18),
        ).pack(side="right", pady=(24, 18))
        tk.Button(
            header,
            text="‹",
            command=lambda: self.shift_selected_day(-1),
            bg=BG,
            fg=MUTED,
            activebackground=GRAY_SOFT,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=7,
            font=(FONT_FALLBACK, 18),
        ).pack(side="right", pady=(24, 18))
        tk.Button(
            header,
            text="⇅",
            command=self.toggle_today_sort,
            bg=BLUE_SOFT if self.today_priority_sort else BG,
            fg=BLUE if self.today_priority_sort else MUTED,
            activebackground=BLUE_SOFT,
            activeforeground=BLUE,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=12,
            pady=7,
            font=(FONT, 15),
        ).pack(side="right", pady=(24, 18))

        quick_wrap = tk.Frame(self.content, bg=BG)
        quick_wrap.pack(fill="x", padx=page_pad, pady=(0, 14))
        if is_real_today:
            quick_surface = RoundedSurface(
                quick_wrap, fill="#F4F6F9", border="#F4F6F9", radius=13, height=66
            )
            quick_surface.pack(fill="x")
            quick = quick_surface.inner
            tk.Label(
                quick, text="＋", bg="#F4F6F9", fg="#9A9EA5", font=(FONT, 20)
            ).pack(side="left", padx=(20, 5))
            placeholder = "添加今天要推进的最小行动"
            quick_var = tk.StringVar(value=placeholder)
            quick_entry = tk.Entry(
                quick,
                textvariable=quick_var,
                bg="#F4F6F9",
                fg="#9A9EA5",
                insertbackground=TEXT,
                relief="flat",
                borderwidth=0,
                font=(FONT, 14),
            )
            quick_entry.pack(side="left", fill="both", expand=True, padx=(0, 18), pady=10)

            def focus_in(_event=None) -> None:
                if quick_var.get() == placeholder:
                    quick_var.set("")
                    quick_entry.configure(fg=TEXT)

            def focus_out(_event=None) -> None:
                if not quick_var.get().strip():
                    quick_var.set(placeholder)
                    quick_entry.configure(fg="#9A9EA5")

            quick_entry.bind("<FocusIn>", focus_in)
            quick_entry.bind("<FocusOut>", focus_out)
            quick_entry.bind(
                "<Return>",
                lambda _event: self.quick_add_today_task(quick_var.get(), placeholder),
            )
        else:
            summary = self.db.daily_summary(selected_iso)
            completed_count = int(summary["completed"] or 0) if summary else 0
            total_count = int(summary["total"] or 0) if summary else 0
            history_surface = RoundedSurface(
                quick_wrap, fill="#F7F8FA", border="#F0F1F3", radius=12, height=54
            )
            history_surface.pack(fill="x")
            history = history_surface.inner
            tk.Label(
                history,
                text=f"历史账本 · 当天完成 {completed_count}/{total_count} · 后续改名不会覆盖这里",
                bg="#F7F8FA",
                fg=MUTED,
                font=(FONT, 11),
            ).pack(side="left", padx=18, pady=15)
            tk.Button(
                history,
                text="回到今天",
                command=self.go_to_today,
                bg="#F7F8FA",
                fg=BLUE,
                activebackground=BLUE_SOFT,
                relief="flat",
                borderwidth=0,
                cursor="hand2",
                font=(FONT, 9),
            ).pack(side="right", padx=16)

        tasks = self.db.list_daily_entries(selected_iso)
        if is_real_today:
            overdue = self.db.list_overdue_entries(selected_iso)
        else:
            overdue = [task for task in tasks if task["state"] in ("planned", "carried")]
        active = [task for task in tasks if task["state"] == "planned"] if is_real_today else []
        completed = [task for task in tasks if task["state"] == "completed"]
        carried = [task for task in tasks if task["state"] == "carried"]
        if self.today_priority_sort:
            priority_rank = {"重要": 0, "普通": 1}
            sorter = lambda task: (
                priority_rank.get(task["priority"], 2),
                task["entry_date"] or "9999-99-99",
                -task["id"],
            )
            overdue.sort(key=sorter)
            active.sort(key=sorter)

        body = ScrollFrame(self.content)
        body.pack(fill="both", expand=True, padx=page_pad, pady=(0, 24))
        if not tasks and not overdue:
            title = "今天还没有行动" if is_real_today else "这一天没有记录"
            detail = "在上方输入一个可以验证的最小行动。" if is_real_today else "可以继续查看相邻日期。"
            self.empty_state(body.body, title, detail)
        else:
            if overdue:
                self.render_today_group(
                    body.body,
                    "已过期" if is_real_today else "当日未完成",
                    overdue,
                    overdue=is_real_today,
                    editable=is_real_today,
                )
            if active:
                self.render_today_group(body.body, "今天", active, editable=True)
            if completed:
                self.render_today_group(
                    body.body, "已完成", completed, completed=True, editable=is_real_today
                )
            if carried and is_real_today:
                self.render_today_group(body.body, "已结转", carried, editable=False)

    def format_day_heading(self, value: date) -> str:
        today = date.today()
        if value == today:
            return "今天"
        if value == today - timedelta(days=1):
            return f"昨天 · {value.month}月{value.day}日"
        weekdays = "一二三四五六日"
        return f"{value.month}月{value.day}日 · 周{weekdays[value.weekday()]}"

    def shift_selected_day(self, delta: int) -> None:
        candidate = self.selected_day + timedelta(days=delta)
        self.selected_day = min(candidate, date.today())
        self.show_view("今日清单")

    def go_to_today(self) -> None:
        self.selected_day = date.today()
        self._observed_local_day = date.today()
        self.show_view("今日清单")

    def open_calendar_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("每日账本")
        dialog.geometry("430x455")
        dialog.resizable(False, False)
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()

        month_cursor = [self.selected_day.replace(day=1)]
        recorded_dates = set(self.db.daily_dates())
        shell = tk.Frame(dialog, bg=BG)
        shell.pack(fill="both", expand=True, padx=22, pady=18)

        def select_day(value: date) -> None:
            self.selected_day = value
            dialog.destroy()
            self.show_view("今日清单")

        def change_month(delta: int) -> None:
            current = month_cursor[0]
            month_index = current.year * 12 + current.month - 1 + delta
            year, month_zero = divmod(month_index, 12)
            candidate = date(year, month_zero + 1, 1)
            if candidate <= date.today().replace(day=1):
                month_cursor[0] = candidate
                draw_month()

        def draw_month() -> None:
            clear(shell)
            current = month_cursor[0]
            top = tk.Frame(shell, bg=BG)
            top.pack(fill="x", pady=(0, 14))
            tk.Button(
                top, text="‹", command=lambda: change_month(-1), bg=BG, fg=MUTED,
                activebackground=GRAY_SOFT, relief="flat", borderwidth=0,
                cursor="hand2", font=(FONT_FALLBACK, 18), width=3,
            ).pack(side="left")
            tk.Label(
                top, text=f"{current.year} 年 {current.month} 月", bg=BG, fg=TEXT,
                font=(FONT, 13, "bold"),
            ).pack(side="left", expand=True)
            tk.Button(
                top, text="›", command=lambda: change_month(1), bg=BG, fg=MUTED,
                activebackground=GRAY_SOFT, relief="flat", borderwidth=0,
                state="normal" if current < date.today().replace(day=1) else "disabled",
                disabledforeground="#D5D7DB", cursor="hand2", font=(FONT_FALLBACK, 18), width=3,
            ).pack(side="right")

            grid = tk.Frame(shell, bg=BG)
            grid.pack(fill="both", expand=True)
            for column, label in enumerate(("一", "二", "三", "四", "五", "六", "日")):
                tk.Label(
                    grid, text=label, bg=BG, fg=MUTED, font=(FONT, 9), width=5,
                ).grid(row=0, column=column, sticky="nsew", pady=(0, 6))
                grid.grid_columnconfigure(column, weight=1)

            weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(current.year, current.month)
            for row_index, week in enumerate(weeks, start=1):
                grid.grid_rowconfigure(row_index, weight=1)
                for column, day_number in enumerate(week):
                    if not day_number:
                        tk.Label(grid, text="", bg=BG).grid(row=row_index, column=column)
                        continue
                    value = date(current.year, current.month, day_number)
                    has_record = value.isoformat() in recorded_dates
                    label = f"{day_number}\n•" if has_record else str(day_number)
                    selected = value == self.selected_day
                    is_today = value == date.today()
                    enabled = value <= date.today()
                    tk.Button(
                        grid,
                        text=label,
                        command=lambda picked=value: select_day(picked),
                        state="normal" if enabled else "disabled",
                        bg=BLUE if selected else (BLUE_SOFT if is_today else BG),
                        fg="white" if selected else (BLUE if has_record or is_today else TEXT),
                        disabledforeground="#D5D7DB",
                        activebackground=BLUE_SOFT,
                        activeforeground=BLUE,
                        relief="flat",
                        borderwidth=0,
                        cursor="hand2",
                        font=(FONT, 9, "bold" if selected or is_today else "normal"),
                        width=5,
                        height=2,
                    ).grid(row=row_index, column=column, sticky="nsew", padx=2, pady=2)

            footer = tk.Frame(shell, bg=BG)
            footer.pack(fill="x", pady=(12, 0))
            tk.Label(
                footer, text="蓝点表示当天有行动记录", bg=BG, fg=MUTED, font=(FONT, 8)
            ).pack(side="left")
            button(footer, "回到今天", lambda: select_day(date.today()), subtle=True).pack(side="right")

        draw_month()

    def quick_add_today_task(self, title: str, placeholder: str) -> None:
        title = title.strip()
        if not title or title == placeholder:
            return
        inbox_id = self.db.get_or_create_inbox()
        self.db.create_task(
            inbox_id,
            title,
            status="今日",
            due_date=datetime.now().date().isoformat(),
            is_today=True,
        )
        self.markdown.sync_all(self.db)
        self.show_view("今日清单")

    def toggle_today_sort(self) -> None:
        self.today_priority_sort = not self.today_priority_sort
        self.show_view("今日清单")

    def open_today_menu(self, anchor: tk.Misc) -> None:
        menu = tk.Menu(
            self,
            tearoff=False,
            bg=BG,
            fg=TEXT,
            activebackground=BLUE_SOFT,
            activeforeground=TEXT,
            font=(FONT, 9),
        )
        menu.add_command(label="新建完整任务", command=self.open_task_dialog)
        menu.add_command(
            label="按优先级排序" if not self.today_priority_sort else "恢复默认排序",
            command=self.toggle_today_sort,
        )
        menu.add_separator()
        menu.add_command(label="打开 Markdown 文档目录", command=self.open_markdown_folder)
        menu.add_command(label="刷新", command=lambda: self.show_view("今日清单"))
        menu.tk_popup(anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height())

    def toggle_today_group(self, title: str) -> None:
        self.today_collapsed[title] = not self.today_collapsed.get(title, False)
        self.show_view("今日清单")

    def render_today_group(
        self,
        parent: tk.Misc,
        title: str,
        tasks,
        *,
        overdue: bool = False,
        completed: bool = False,
        editable: bool = True,
    ) -> None:
        group = tk.Frame(parent, bg=BG)
        group.pack(fill="x", pady=(8, 12))
        group_head = tk.Frame(group, bg=BG, height=48)
        group_head.pack(fill="x")
        group_head.pack_propagate(False)
        collapsed = self.today_collapsed.get(title, False)
        chevron = tk.Canvas(
            group_head, width=24, height=44, bg=BG, highlightthickness=0, cursor="hand2"
        )
        chevron.pack(side="left", padx=(0, 2))
        if collapsed:
            chevron.create_line(9, 17, 14, 22, 9, 27, fill="#A0A4AA", width=1.5)
        else:
            chevron.create_line(7, 20, 12, 25, 17, 20, fill="#A0A4AA", width=1.5)
        chevron.bind("<Button-1>", lambda _event: self.toggle_today_group(title))
        tk.Label(
            group_head,
            text=title,
            bg=BG,
            fg=TEXT,
            font=(FONT, 13, "bold"),
        ).pack(side="left")
        tk.Label(
            group_head,
            text=str(len(tasks)),
            bg=BG,
            fg="#A0A4AA",
            font=(FONT, 11),
        ).pack(side="left", padx=10)
        if overdue and editable:
            tk.Button(
                group_head,
                text="顺延",
                command=lambda: self.postpone_overdue(tasks),
                bg=BG,
                fg="#3D73FF",
                activebackground=BLUE_SOFT,
                activeforeground=BLUE,
                relief="flat",
                borderwidth=0,
                cursor="hand2",
                padx=8,
                pady=5,
                font=(FONT, 9),
            ).pack(side="right", padx=4)
        if collapsed:
            return
        for task in tasks:
            self.render_today_task_row(
                group, task, overdue=overdue, completed=completed, editable=editable
            )

    def render_today_task_row(
        self,
        parent: tk.Misc,
        task,
        *,
        overdue: bool = False,
        completed: bool = False,
        editable: bool = True,
    ) -> None:
        row = RoundedSurface(
            parent,
            fill=BG,
            border="#E1E3E7",
            radius=11,
            shadow=True,
            height=66,
            cursor="hand2",
        )
        row.pack(fill="x", padx=3, pady=5)
        content = row.inner

        checkbox = tk.Canvas(content, width=36, height=36, bg=BG, highlightthickness=0, cursor="hand2")
        checkbox.pack(side="left", padx=(21, 6), pady=14)
        outline = task["mainline_color"] or "#A6A9AE"
        if task["priority"] == "重要":
            outline = "#F2A000"
        if completed:
            checkbox.create_rectangle(7, 7, 27, 27, fill="#D1D3D6", outline="#D1D3D6", width=2)
            checkbox.create_line(12, 17, 16, 21, 23, 13, fill="white", width=2, capstyle="round", joinstyle="round")
        else:
            checkbox.create_rectangle(7, 7, 27, 27, fill=BG, outline=outline, width=2)
        if editable:
            checkbox.bind(
                "<Button-1>",
                lambda _event, eid=task["id"], value=not completed: self.set_today_task_completed(eid, value),
            )

        title_color = "#B9BBC0" if completed else TEXT
        title = tk.Label(
            content,
            text=task["title"],
            bg=BG,
            fg=title_color,
            anchor="w",
            font=(FONT, 13),
            cursor="hand2",
        )
        title.pack(side="left", fill="both", expand=True, pady=14)
        if task["task_id"]:
            title.bind(
                "<Button-1>",
                lambda _event, tid=task["task_id"]: self.open_task_detail(tid),
            )

        due_text = ""
        due_color = "#D0D2D6" if completed else MUTED
        if completed:
            completed_at = task["completed_at"] or ""
            due_text = completed_at[11:16] if len(completed_at) >= 16 else "已完成"
        elif overdue:
            yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
            due_text = "昨天" if task["entry_date"] == yesterday else task["entry_date"][5:]
            due_color = "#FF4D4F"
        elif task["entry_date"] == datetime.now().date().isoformat():
            due_text = "今天"
            due_color = "#3D73FF"
        elif task["entry_date"]:
            due_text = task["entry_date"][5:]

        meta = tk.Frame(content, bg=BG)
        meta.pack(side="right", padx=(8, 10), pady=14)
        tk.Label(
            meta,
            text=due_text,
            bg=BG,
            fg=due_color,
            font=(FONT, 10),
        ).pack(side="right", padx=(8, 0))
        if task["task_id"]:
            tk.Button(
                meta,
                text="▤",
                command=lambda tid=task["task_id"]: self.open_markdown_editor("task", tid),
                bg=BG,
                fg="#D0D2D6" if completed else "#A9ADB3",
                activebackground=BG,
                activeforeground=BLUE,
                relief="flat",
                borderwidth=0,
                cursor="hand2",
                padx=3,
                font=(FONT, 10),
            ).pack(side="right")
        tk.Label(
            meta,
            text=task["mainline_name"],
            bg=BG,
            fg="#D0D2D6" if completed else "#999DA4",
            font=(FONT, 10),
        ).pack(side="right", padx=(0, 3))

    def set_today_task_completed(self, entry_id: int, completed: bool) -> None:
        self.db.set_daily_entry_completed(entry_id, completed)
        self.markdown.sync_all(self.db)
        self.show_view("今日清单")

    def postpone_overdue(self, tasks) -> None:
        self.db.carry_daily_entries((task["id"] for task in tasks), date.today().isoformat())
        self.markdown.sync_all(self.db)
        self.show_view("今日清单")

    def render_execution(self) -> None:
        self.page_header("执行区", action_text="＋ 记录灵感", action=self.open_thought_dialog)
        compact = self.layout_mode == "compact"
        page_pad = self.reading_padding(target_width=1260, minimum=34)
        body = tk.Frame(self.content, bg=BG)
        body.pack(fill="both", expand=True, padx=page_pad, pady=24)
        body.grid_columnconfigure(0, weight=1)
        tasks_panel = ScrollFrame(body)
        thoughts_panel = ScrollFrame(body)
        task_title = tk.Label(
            body, text="正在执行的任务", bg=BG, fg=TEXT, font=(FONT, 14, "bold")
        )
        thought_title = tk.Label(
            body, text="正在验证的思路", bg=BG, fg=TEXT, font=(FONT, 14, "bold")
        )
        if compact:
            body.grid_rowconfigure(1, weight=1, uniform="execution_rows")
            body.grid_rowconfigure(3, weight=1, uniform="execution_rows")
            task_title.grid(row=0, column=0, sticky="w", pady=(0, 10))
            tasks_panel.grid(row=1, column=0, sticky="nsew", pady=(0, 18))
            thought_title.grid(row=2, column=0, sticky="w", pady=(0, 10))
            thoughts_panel.grid(row=3, column=0, sticky="nsew")
        else:
            body.grid_columnconfigure(1, weight=1)
            body.grid_rowconfigure(1, weight=1)
            task_title.grid(row=0, column=0, sticky="w", padx=(0, 18), pady=(0, 12))
            thought_title.grid(row=0, column=1, sticky="w", padx=(18, 0), pady=(0, 12))
            tasks_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 18))
            thoughts_panel.grid(row=1, column=1, sticky="nsew", padx=(18, 0))
        tasks = self.db.list_tasks(status="执行中")
        thoughts = self.db.list_thoughts(statuses=("验证中",))
        for task in tasks:
            self.render_task_row(tasks_panel.body, task, show_mainline=True)
        for thought in thoughts:
            self.render_execution_thought(thoughts_panel.body, thought)
        if not tasks:
            self.empty_state(tasks_panel.body, "没有执行中的任务", "从主线看板推进一个任务。")
        if not thoughts:
            self.empty_state(thoughts_panel.body, "没有验证中的思路", "整理思路后开始一次验证。")

    def render_task_row(self, parent: tk.Misc, task, *, show_mainline: bool = False) -> None:
        surface = RoundedSurface(
            parent, fill=BG, border="#E0E3E7", radius=12, shadow=True
        )
        surface.pack(fill="x", padx=3, pady=7)
        row = surface.inner
        tk.Label(
            row, text="○", bg=BG, fg=GREEN if task["status"] == "执行中" else MUTED, font=(FONT, 16)
        ).pack(side="left", padx=(14, 10), pady=15)
        texts = tk.Frame(row, bg=BG)
        texts.pack(side="left", fill="both", expand=True, pady=11)
        tk.Label(texts, text=task["title"], bg=BG, fg=TEXT, anchor="w", font=(FONT, 12, "bold")).pack(fill="x")
        meta = task["mainline_name"] if show_mainline else task["status"]
        tk.Label(texts, text=meta, bg=BG, fg=MUTED, anchor="w", font=(FONT, 10)).pack(fill="x", pady=(4, 0))
        if task["status"] != "完成":
            button(row, "完成", lambda tid=task["id"]: self.move_task(tid, "完成"), subtle=True).pack(
                side="right", padx=12
            )
        button(
            row,
            "今日 ✓" if task["is_today"] else "加入今日",
            lambda tid=task["id"], flag=not bool(task["is_today"]): self.toggle_today(tid, flag),
            subtle=True,
        ).pack(side="right", padx=5)
        button(
            row,
            "MD",
            lambda tid=task["id"]: self.open_markdown_editor("task", tid),
            subtle=True,
            width=3,
        ).pack(side="right", padx=5)

    def toggle_today(self, task_id: int, is_today: bool) -> None:
        self.db.set_task_today(task_id, is_today)
        self.show_view(self.current_view)

    def render_execution_thought(self, parent: tk.Misc, thought) -> None:
        surface = RoundedSurface(
            parent, fill=BG, border="#E0E3E7", radius=12, shadow=True, cursor="hand2"
        )
        surface.pack(fill="x", padx=3, pady=7)
        row = surface.inner
        top = tk.Frame(row, bg=BG)
        top.pack(fill="x", padx=14, pady=(13, 7))
        tk.Label(top, text=thought["title"], bg=BG, fg=TEXT, font=(FONT, 12, "bold")).pack(side="left")
        tk.Label(top, text=f"{thought['progress']}%", bg=GREEN_SOFT, fg=GREEN, padx=8, pady=3, font=(FONT, 10)).pack(side="right")
        ttk.Progressbar(row, maximum=100, value=thought["progress"]).pack(fill="x", padx=14, pady=(0, 9))
        tk.Label(
            row,
            text=f"下一步：{thought['next_step'] or '尚未填写'}",
            bg=BG,
            fg=MUTED,
            anchor="w",
            wraplength=max(
                420,
                self.estimated_content_width()
                - (150 if self.layout_mode == "compact" else 760),
            ),
            font=(FONT, 11),
        ).pack(fill="x", padx=14, pady=(0, 12))
        button(row, "记录执行", lambda tid=thought["id"]: self.open_log_dialog(tid), primary=True).pack(anchor="e", padx=14, pady=(0, 13))
        button(
            row,
            "MD 思路文档",
            lambda tid=thought["id"]: self.open_markdown_editor("thought", tid),
            subtle=True,
        ).pack(anchor="e", padx=14, pady=(0, 13))

    def empty_state(self, parent: tk.Misc, title: str, detail: str) -> None:
        holder = tk.Frame(parent, bg=BG)
        holder.pack(fill="x", pady=46)
        tk.Label(holder, text=title, bg=BG, fg=TEXT, font=(FONT, 12, "bold")).pack()
        tk.Label(holder, text=detail, bg=BG, fg=MUTED, font=(FONT, 9)).pack(pady=7)

    # --------------------------- Thought organizer ---------------------------
    def render_thoughts(self) -> None:
        header = self.page_header(
            "思路整理", action_text="＋ 捕获灵感", action=self.open_thought_dialog
        )
        picker = self.mainline_picker(header)
        picker.pack(side="left", pady=(28, 22))

        workspace = tk.Frame(self.content, bg=BG)
        workspace.pack(fill="both", expand=True)
        compact = self.layout_mode == "compact"

        queue_panel = tk.Frame(
            workspace, bg=BG, highlightthickness=1, highlightbackground=BORDER
        )
        editor_panel = tk.Frame(
            workspace, bg=BG, highlightthickness=1, highlightbackground=BORDER
        )
        log_panel = tk.Frame(
            workspace, bg=BG, highlightthickness=1, highlightbackground=BORDER
        )
        if compact:
            workspace.grid_columnconfigure(0, weight=30, minsize=260)
            workspace.grid_columnconfigure(1, weight=70, minsize=520)
            workspace.grid_rowconfigure(0, weight=58)
            workspace.grid_rowconfigure(1, weight=42)
            queue_panel.grid(row=0, column=0, rowspan=2, sticky="nsew")
            editor_panel.grid(row=0, column=1, sticky="nsew")
            log_panel.grid(row=1, column=1, sticky="nsew")
        else:
            workspace.grid_columnconfigure(0, weight=22, minsize=250)
            workspace.grid_columnconfigure(1, weight=48, minsize=500)
            workspace.grid_columnconfigure(2, weight=30, minsize=330)
            workspace.grid_rowconfigure(0, weight=1)
            queue_panel.grid(row=0, column=0, sticky="nsew")
            editor_panel.grid(row=0, column=1, sticky="nsew")
            log_panel.grid(row=0, column=2, sticky="nsew")

        thoughts = self.db.list_thoughts(self.selected_mainline_id)
        if self.selected_thought_id not in {row["id"] for row in thoughts}:
            validating = [row for row in thoughts if row["status"] == "验证中"]
            pending = [row for row in thoughts if row["status"] == "待整理"]
            first = validating[0] if validating else (pending[0] if pending else (thoughts[0] if thoughts else None))
            self.selected_thought_id = first["id"] if first else None

        self.render_thought_queue(queue_panel, thoughts)
        self.render_thought_editor(editor_panel)
        self.render_log_panel(log_panel)

    def render_thought_queue(self, parent: tk.Misc, thoughts) -> None:
        head = tk.Frame(parent, bg=BG, height=56)
        head.pack(fill="x")
        head.pack_propagate(False)
        pending_count = sum(1 for row in thoughts if row["status"] == "待整理")
        tk.Label(
            head, text=f"待整理  {pending_count}", bg=BG, fg=TEXT, font=(FONT, 12, "bold")
        ).pack(side="left", padx=20, pady=17)
        scroll = ScrollFrame(parent)
        scroll.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for thought in thoughts:
            selected = thought["id"] == self.selected_thought_id
            card = RoundedSurface(
                scroll.body,
                fill="#EDF2FF" if selected else BG,
                border="#C8D8FF" if selected else "#E1E3E7",
                radius=12,
                shadow=not selected,
                cursor="hand2",
            )
            card.pack(fill="x", padx=3, pady=6)
            inner = tk.Frame(card.inner, bg="#EDF2FF" if selected else BG)
            inner.pack(fill="both", expand=True, padx=13, pady=12)
            tk.Label(
                inner,
                text=thought["title"],
                bg="#EDF2FF" if selected else BG,
                fg=TEXT,
                anchor="w",
                justify="left",
                wraplength=210,
                font=(FONT, 11, "bold"),
            ).pack(fill="x")
            meta = tk.Frame(inner, bg="#EDF2FF" if selected else BG)
            meta.pack(fill="x", pady=(8, 0))
            status_color = GREEN if thought["status"] in ("验证中", "已落地") else MUTED
            tk.Label(
                meta,
                text=thought["status"],
                bg=GREEN_SOFT if thought["status"] in ("验证中", "已落地") else GRAY_SOFT,
                fg=status_color,
                padx=7,
                pady=3,
                font=(FONT, 10),
            ).pack(side="left")
            tk.Label(
                meta,
                text=thought["updated_at"][:10],
                bg="#EDF2FF" if selected else BG,
                fg=MUTED,
                font=(FONT, 10),
            ).pack(side="right")
            bind_click(card, lambda _e, tid=thought["id"]: self.select_thought(tid))
        button(
            scroll.body, "＋ 捕获灵感", self.open_thought_dialog, subtle=True
        ).pack(anchor="w", pady=10)

    def select_thought(self, thought_id: int) -> None:
        self.selected_thought_id = thought_id
        self.show_view("思路整理")

    def render_thought_editor(self, parent: tk.Misc) -> None:
        if not self.selected_thought_id:
            self.empty_state(parent, "还没有思路", "先捕获一条灵感，再开始整理。")
            return
        thought = self.db.get_thought(self.selected_thought_id)
        if not thought:
            return
        scroll = ScrollFrame(parent)
        scroll.pack(fill="both", expand=True)
        body = scroll.body
        tk.Label(
            body, text="结构化思路", bg=BG, fg=TEXT, font=(FONT, 12, "bold")
        ).pack(anchor="w", padx=22, pady=(18, 12))

        title_var = tk.StringVar(value=thought["title"])
        title_entry = entry(body, title_var)
        title_entry.configure(font=(FONT, 18, "bold"))
        title_entry.pack(fill="x", padx=22, ipady=10)

        meta = tk.Frame(body, bg=BG)
        meta.pack(fill="x", padx=22, pady=12)
        tk.Label(meta, text="状态", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left")
        status_var = tk.StringVar(value=thought["status"])
        status_combo = ttk.Combobox(
            meta, values=THOUGHT_STATUSES, textvariable=status_var, state="readonly", width=9
        )
        status_combo.pack(side="left", padx=(7, 20))
        tk.Label(meta, text="进度", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left")
        progress_var = tk.IntVar(value=thought["progress"])
        progress_spin = tk.Spinbox(
            meta,
            from_=0,
            to=100,
            increment=5,
            textvariable=progress_var,
            width=5,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            font=(FONT, 9),
        )
        progress_spin.pack(side="left", padx=7, ipady=5)
        tk.Label(meta, text="%", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left")

        fields: dict[str, tk.Text] = {}
        for label, key, value, height in (
            ("原始灵感", "raw_content", thought["raw_content"], 3),
            ("结论", "conclusion", thought["conclusion"], 3),
            ("依据", "evidence", thought["evidence"], 4),
            ("下一步", "next_step", thought["next_step"], 3),
        ):
            box = tk.Frame(body, bg=BG)
            box.pack(fill="x", padx=22, pady=6)
            tk.Label(box, text=label, bg=BG, fg=TEXT, font=(FONT, 11, "bold")).pack(
                anchor="w", pady=(0, 6)
            )
            fields[key] = text_box(box, value, height)
            fields[key].pack(fill="x")

        save = lambda: self.save_thought_form(
            thought["id"], title_var.get(), fields, status_var.get(), progress_var.get()
        )
        button(body, "保存整理", save, primary=True).pack(anchor="e", padx=22, pady=(8, 20))
        button(
            body,
            "MD 打开思路文档",
            lambda tid=thought["id"]: self.open_markdown_editor("thought", tid),
        ).pack(anchor="e", padx=22, pady=(0, 16))

        separator = tk.Frame(body, bg=BORDER, height=1)
        separator.pack(fill="x", padx=22)
        tk.Label(body, text="关联", bg=BG, fg=TEXT, font=(FONT, 12, "bold")).pack(
            anchor="w", padx=22, pady=(18, 10)
        )

        relation_surface = RoundedSurface(
            body, fill=BG, border="#E0E3E7", radius=12, shadow=True
        )
        relation_surface.pack(fill="x", padx=22)
        relation_holder = relation_surface.inner
        self.relation_row(relation_holder, "属于主线", thought["mainline_name"] or "未关联")
        for task in self.db.linked_tasks(thought["id"]):
            self.relation_row(relation_holder, "关联任务", task["title"])
        for relation in self.db.thought_relations(thought["id"]):
            other = relation["target_title"] if relation["source_thought_id"] == thought["id"] else relation["source_title"]
            self.relation_row(relation_holder, relation["relation"], other)

        actions = tk.Frame(body, bg=BG)
        actions.pack(fill="x", padx=22, pady=12)
        button(
            actions,
            "＋ 生成任务",
            lambda tid=thought["id"]: self.generate_task(tid),
            primary=True,
        ).pack(side="left")
        button(
            actions,
            "＋ 关联任务",
            lambda tid=thought["id"]: self.open_link_task_dialog(tid),
        ).pack(side="left", padx=8)
        button(
            actions,
            "＋ 关联思路",
            lambda tid=thought["id"]: self.open_link_thought_dialog(tid),
        ).pack(side="left")

    def relation_row(self, parent: tk.Misc, relation: str, target: str) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=12, pady=9)
        tk.Label(row, text=relation, width=10, anchor="w", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left")
        tk.Label(row, text=target, anchor="w", bg=BG, fg=TEXT, font=(FONT, 9)).pack(side="left", fill="x", expand=True)

    def save_thought_form(
        self,
        thought_id: int,
        title: str,
        fields: dict[str, tk.Text],
        status: str,
        progress: int,
    ) -> None:
        if not title.strip():
            messagebox.showwarning("缺少标题", "请为思路填写标题。", parent=self)
            return
        self.db.update_thought(
            thought_id,
            title=title,
            raw_content=fields["raw_content"].get("1.0", "end").strip(),
            conclusion=fields["conclusion"].get("1.0", "end").strip(),
            evidence=fields["evidence"].get("1.0", "end").strip(),
            next_step=fields["next_step"].get("1.0", "end").strip(),
            status=status,
            progress=progress,
            mainline_id=self.selected_mainline_id,
        )
        self.show_view("思路整理")

    def render_log_panel(self, parent: tk.Misc) -> None:
        head = tk.Frame(parent, bg=BG, height=56)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="执行记录", bg=BG, fg=TEXT, font=(FONT, 12, "bold")).pack(side="left", padx=20, pady=17)
        if not self.selected_thought_id:
            return
        button(
            head,
            "＋ 记录",
            lambda: self.open_log_dialog(self.selected_thought_id),
            primary=True,
        ).pack(side="right", padx=12, pady=9)
        logs = self.db.execution_logs(self.selected_thought_id)
        scroll = ScrollFrame(parent)
        scroll.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        if not logs:
            self.empty_state(scroll.body, "尚无执行记录", "记录第一次行动、结果和下一步。")
        for index, log in enumerate(logs):
            item = tk.Frame(scroll.body, bg=BG)
            item.pack(fill="x", pady=(4, 10))
            rail = tk.Frame(item, bg=BLUE if index == 0 else "#B7BBC2", width=2)
            rail.pack(side="left", fill="y", padx=(5, 12))
            detail = tk.Frame(item, bg=BG)
            detail.pack(side="left", fill="both", expand=True)
            log_head = tk.Frame(detail, bg=BG)
            log_head.pack(fill="x", pady=(0, 8))
            tk.Label(
                log_head,
                text=f"●  {log['created_at'][:16]}     {log['progress']}%",
                bg=BG,
                fg=BLUE if index == 0 else MUTED,
                anchor="w",
                font=(FONT, 9, "bold"),
            ).pack(side="left", fill="x", expand=True)
            button(
                log_head,
                "MD",
                lambda lid=log["id"]: self.open_markdown_editor("execution", lid),
                subtle=True,
                width=3,
            ).pack(side="right")
            for label, key in (
                ("本次行动", "action"),
                ("执行结果", "result"),
                ("遇到阻碍", "blocker"),
                ("下一步", "next_step"),
            ):
                if log[key]:
                    text = tk.Frame(detail, bg=BG)
                    text.pack(fill="x", pady=3)
                    tk.Label(text, text=label, width=8, anchor="w", bg=BG, fg=TEXT, font=(FONT, 8, "bold")).pack(side="left")
                    tk.Label(text, text=log[key], anchor="w", justify="left", wraplength=250, bg=BG, fg=MUTED, font=(FONT, 8)).pack(side="left", fill="x", expand=True)
            tk.Frame(detail, bg=BORDER, height=1).pack(fill="x", pady=(12, 0))

    # --------------------------- Review queue ---------------------------
    def render_review(self) -> None:
        self.page_header("候审区", action_text="＋ 捕获灵感", action=self.open_thought_dialog)
        thoughts = self.db.list_thoughts(statuses=("待整理",))
        page_pad = self.reading_padding(target_width=1160, minimum=34)
        body = ScrollFrame(self.content)
        body.pack(fill="both", expand=True, padx=page_pad, pady=24)
        tk.Label(body.body, text=f"等待整理的灵感  {len(thoughts)}", bg=BG, fg=TEXT, font=(FONT, 15, "bold")).pack(anchor="w", pady=(0, 14))
        tk.Label(body.body, text="先捕获，不急着执行。整理后再决定关联主线、生成任务或搁置。", bg=BG, fg=MUTED, font=(FONT, 11)).pack(anchor="w", pady=(0, 18))
        for thought in thoughts:
            surface = RoundedSurface(
                body.body, fill=BG, border="#E0E3E7", radius=13, shadow=True
            )
            surface.pack(fill="x", padx=3, pady=8)
            card = surface.inner
            text = tk.Frame(card, bg=BG)
            text.pack(side="left", fill="both", expand=True, padx=16, pady=14)
            tk.Label(text, text=thought["title"], bg=BG, fg=TEXT, anchor="w", font=(FONT, 13, "bold")).pack(fill="x")
            tk.Label(
                text,
                text=thought["raw_content"],
                bg=BG,
                fg=MUTED,
                anchor="w",
                wraplength=max(380, self.estimated_content_width() - 560),
                justify="left",
                font=(FONT, 11),
            ).pack(fill="x", pady=(6, 0))
            button(card, "开始整理", lambda tid=thought["id"]: self.start_organizing(tid), primary=True).pack(side="right", padx=16)
            button(
                card,
                "MD",
                lambda tid=thought["id"]: self.open_markdown_editor("thought", tid),
                subtle=True,
                width=3,
            ).pack(side="right", padx=5)
            button(card, "搁置", lambda tid=thought["id"]: self.shelve_thought(tid), subtle=True).pack(side="right")
        if not thoughts:
            self.empty_state(body.body, "候审区已经清空", "新的灵感会先来到这里。")

    def start_organizing(self, thought_id: int) -> None:
        self.selected_thought_id = thought_id
        self.show_view("思路整理")

    def shelve_thought(self, thought_id: int) -> None:
        thought = self.db.get_thought(thought_id)
        if not thought:
            return
        self.db.update_thought(
            thought_id,
            title=thought["title"],
            raw_content=thought["raw_content"],
            conclusion=thought["conclusion"],
            evidence=thought["evidence"],
            next_step=thought["next_step"],
            status="已搁置",
            progress=thought["progress"],
            mainline_id=thought["mainline_id"],
        )
        self.show_view("候审区")

    # --------------------------- Markdown documents ---------------------------
    def open_markdown_folder(self) -> None:
        self.markdown.sync_all(self.db)
        path = self.markdown.root.resolve()
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror("无法打开文档目录", str(exc), parent=self)

    def open_external_markdown(self, path: Path) -> None:
        """Prefer the open-source MarkText editor, then use the OS association."""
        candidates: list[str] = []
        for name in ("marktext", "MarkText"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
        local_app_data = os.environ.get("LOCALAPPDATA")
        program_files = os.environ.get("PROGRAMFILES")
        if local_app_data:
            candidates.extend(
                [
                    str(Path(local_app_data) / "Programs" / "MarkText" / "MarkText.exe"),
                    str(Path(local_app_data) / "Programs" / "marktext" / "MarkText.exe"),
                ]
            )
        if program_files:
            candidates.append(str(Path(program_files) / "MarkText" / "MarkText.exe"))
        try:
            executable = next((candidate for candidate in candidates if Path(candidate).exists()), None)
            if executable:
                subprocess.Popen([executable, str(path)])
            elif sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror(
                "无法打开外部编辑器",
                f"可以安装 MarkText，或为 .md 文件设置默认程序。\n\n{exc}",
                parent=self,
            )

    def open_markdown_editor(self, kind: str, object_id: int) -> tk.Toplevel | None:
        self.markdown.sync_all(self.db)
        path = self.markdown.path_for(kind, object_id).resolve()
        if not path.exists():
            messagebox.showerror("文档不存在", str(path), parent=self)
            return

        win = tk.Toplevel(self)
        win.title(f"Markdown · {path.name}")
        win.geometry("1240x790")
        win.minsize(900, 600)
        win.configure(bg=BG)
        win.transient(self)

        header = tk.Frame(win, bg=BG, height=82)
        header.pack(fill="x")
        header.pack_propagate(False)
        title_area = tk.Frame(header, bg=BG)
        title_area.pack(side="left", fill="both", expand=True, padx=24, pady=13)
        tk.Label(
            title_area,
            text=f"Markdown 文档 · {path.stem}",
            bg=BG,
            fg=TEXT,
            font=(FONT, 15, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            title_area,
            text=f"{path}   ·   系统同步区会自动更新，下方自由记录不会被覆盖",
            bg=BG,
            fg=MUTED,
            font=(FONT, 8),
            anchor="w",
        ).pack(fill="x", pady=(5, 0))

        actions = tk.Frame(header, bg=BG)
        actions.pack(side="right", padx=20, pady=16)
        button(actions, "外部打开", lambda: self.open_external_markdown(path)).pack(
            side="left", padx=5
        )

        paned = tk.PanedWindow(
            win,
            orient="horizontal",
            bg=BORDER,
            sashwidth=4,
            sashrelief="flat",
            borderwidth=0,
        )
        paned.pack(fill="both", expand=True)
        source_panel = tk.Frame(paned, bg=BG)
        preview_panel = tk.Frame(paned, bg=BG)
        paned.add(source_panel, minsize=380, stretch="always")
        paned.add(preview_panel, minsize=380, stretch="always")

        source_head = tk.Frame(source_panel, bg=GRAY_SOFT, height=38)
        source_head.pack(fill="x")
        source_head.pack_propagate(False)
        tk.Label(source_head, text="Markdown 源文档", bg=GRAY_SOFT, fg=TEXT, font=(FONT, 9, "bold")).pack(
            side="left", padx=14, pady=9
        )
        preview_head = tk.Frame(preview_panel, bg=GRAY_SOFT, height=38)
        preview_head.pack(fill="x")
        preview_head.pack_propagate(False)
        tk.Label(preview_head, text="实时预览", bg=GRAY_SOFT, fg=TEXT, font=(FONT, 9, "bold")).pack(
            side="left", padx=14, pady=9
        )

        source_wrap = tk.Frame(source_panel, bg=BG)
        source_wrap.pack(fill="both", expand=True)
        source_scroll = ttk.Scrollbar(source_wrap, orient="vertical")
        source = tk.Text(
            source_wrap,
            wrap="word",
            undo=True,
            maxundo=-1,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=BLUE_SOFT,
            selectforeground=TEXT,
            relief="flat",
            borderwidth=0,
            padx=18,
            pady=16,
            spacing1=2,
            spacing3=2,
            font=(FONT, 10),
            yscrollcommand=source_scroll.set,
        )
        source_scroll.configure(command=source.yview)
        source.pack(side="left", fill="both", expand=True)
        source_scroll.pack(side="right", fill="y")
        initial = path.read_text(encoding="utf-8")
        source.insert("1.0", initial)

        if HtmlFrame is not None and markdown2 is not None:
            preview = HtmlFrame(
                preview_panel,
                messages_enabled=False,
                javascript_enabled=False,
                images_enabled=True,
                vertical_scrollbar="auto",
                horizontal_scrollbar=False,
                selection_enabled=True,
            )
            preview.pack(fill="both", expand=True)
        else:
            preview = tk.Text(
                preview_panel,
                wrap="word",
                bg=BG,
                fg=MUTED,
                relief="flat",
                padx=18,
                pady=16,
                font=(FONT, 10),
            )
            preview.pack(fill="both", expand=True)

        last_saved = [initial]
        update_job: list[str | None] = [None]

        def render_preview() -> None:
            update_job[0] = None
            markdown_source = source.get("1.0", "end-1c")
            if HtmlFrame is not None and markdown2 is not None and hasattr(preview, "load_html"):
                content = markdown2.markdown(
                    markdown_source,
                    extras=(
                        "fenced-code-blocks",
                        "tables",
                        "strike",
                        "task_list",
                        "footnotes",
                        "metadata",
                    ),
                )
                html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
                    body {{ background:#fff; color:#17191f; font-family:'Microsoft YaHei UI','Segoe UI',sans-serif;
                           font-size:15px; line-height:1.75; padding:24px 34px; max-width:860px; }}
                    h1 {{ font-size:30px; margin:0 0 18px; }} h2 {{ font-size:21px; margin-top:28px; }}
                    h3 {{ font-size:17px; margin-top:22px; }} a {{ color:#1976e9; }}
                    blockquote {{ color:#667085; border-left:3px solid #d9e8ff; margin-left:0; padding-left:14px; }}
                    code {{ background:#f5f6f7; padding:2px 5px; }} pre {{ background:#f5f6f7; padding:14px; }}
                    table {{ border-collapse:collapse; }} th,td {{ border:1px solid #e5e7eb; padding:7px 10px; }}
                    hr {{ border:0; border-top:1px solid #e5e7eb; }}
                </style></head><body>{content}</body></html>"""
                preview.load_html(html, base_url=path.parent.as_uri() + "/")
            else:
                preview.configure(state="normal")
                preview.delete("1.0", "end")
                preview.insert(
                    "1.0",
                    "实时渲染组件未安装，仍可正常编辑 Markdown 源文档。\n\n" + markdown_source,
                )
                preview.configure(state="disabled")

        def schedule_preview(_event=None) -> None:
            if update_job[0] is not None:
                win.after_cancel(update_job[0])
            update_job[0] = win.after(280, render_preview)

        def save() -> None:
            content = source.get("1.0", "end-1c")
            self.markdown.write_user_edited(kind, object_id, content)
            last_saved[0] = content
            render_preview()

        def close_editor() -> None:
            content = source.get("1.0", "end-1c")
            if content != last_saved[0]:
                answer = messagebox.askyesnocancel(
                    "保存 Markdown？", "文档有未保存修改，关闭前要保存吗？", parent=win
                )
                if answer is None:
                    return
                if answer:
                    save()
            win.destroy()

        button(actions, "保存  Ctrl+S", save, primary=True).pack(side="left", padx=5)
        source.bind("<KeyRelease>", schedule_preview)
        win.bind("<Control-s>", lambda _event: save())
        win.protocol("WM_DELETE_WINDOW", close_editor)
        win.after(120, render_preview)
        source.focus_set()
        return win

    # --------------------------- Dialogs and actions ---------------------------
    def dialog(self, title: str, size: str) -> tuple[tk.Toplevel, tk.Frame]:
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry(size)
        win.configure(bg=BG)
        win.transient(self)
        win.grab_set()
        win.update_idletasks()
        x = self.winfo_rootx() + max(40, (self.winfo_width() - win.winfo_width()) // 2)
        y = self.winfo_rooty() + max(40, (self.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"+{x}+{y}")
        tk.Label(win, text=title, bg=BG, fg=TEXT, font=(FONT, 18, "bold")).pack(
            anchor="w", padx=28, pady=(24, 16)
        )
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x")
        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=28, pady=20)
        return win, body

    def form_label(self, parent: tk.Misc, text: str) -> None:
        tk.Label(parent, text=text, bg=BG, fg=TEXT, font=(FONT, 9, "bold")).pack(
            anchor="w", pady=(8, 5)
        )

    def open_mainline_dialog(self) -> None:
        win, body = self.dialog("新建主线", "520x390")
        self.form_label(body, "主线名称")
        name_var = tk.StringVar()
        name = entry(body, name_var)
        name.pack(fill="x", ipady=8)
        name.focus_set()
        self.form_label(body, "愿景 / 完成标准")
        vision = text_box(body, height=5)
        vision.pack(fill="x")

        def save() -> None:
            if not name_var.get().strip():
                messagebox.showwarning("缺少名称", "请填写主线名称。", parent=win)
                return
            self.db.create_mainline(
                name_var.get(), vision.get("1.0", "end")
            )
            win.destroy()
            self.show_view("主线保管箱")

        button(body, "创建主线", save, primary=True).pack(anchor="e", pady=18)

    def open_task_dialog(self, default_status: str = "待执行") -> None:
        win, body = self.dialog("新建任务", "590x690")
        mainlines = self.db.list_mainlines()
        names = [row["name"] for row in mainlines]
        ids = {row["name"]: row["id"] for row in mainlines}
        current_name = next(
            (row["name"] for row in mainlines if row["id"] == self.selected_mainline_id), names[0]
        )
        title_var = tk.StringVar()
        line_var = tk.StringVar(value=current_name)
        status_var = tk.StringVar(value=default_status)
        priority_var = tk.StringVar(value="普通")
        due_var = tk.StringVar()
        today_var = tk.BooleanVar(value=default_status == "今日")
        next_action_var = tk.StringVar()

        self.form_label(body, "任务标题")
        title_entry = entry(body, title_var)
        title_entry.pack(fill="x", ipady=8)
        title_entry.focus_set()
        self.form_label(body, "任务说明")
        description = text_box(body, height=4)
        description.pack(fill="x")
        self.form_label(body, "下一次可以真正动手做什么（可选）")
        next_action = entry(body, next_action_var)
        next_action.pack(fill="x")
        form_row = tk.Frame(body, bg=BG)
        form_row.pack(fill="x", pady=6)
        left = tk.Frame(form_row, bg=BG)
        left.pack(side="left", fill="x", expand=True, padx=(0, 8))
        right = tk.Frame(form_row, bg=BG)
        right.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.form_label(left, "所属主线")
        ttk.Combobox(left, values=names, textvariable=line_var, state="readonly").pack(fill="x")
        self.form_label(right, "状态")
        ttk.Combobox(right, values=TASK_STATUSES, textvariable=status_var, state="readonly").pack(fill="x")
        form_row2 = tk.Frame(body, bg=BG)
        form_row2.pack(fill="x")
        left2 = tk.Frame(form_row2, bg=BG)
        left2.pack(side="left", fill="x", expand=True, padx=(0, 8))
        right2 = tk.Frame(form_row2, bg=BG)
        right2.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.form_label(left2, "优先级")
        ttk.Combobox(left2, values=("普通", "重要"), textvariable=priority_var, state="readonly").pack(fill="x")
        self.form_label(right2, "截止日期（YYYY-MM-DD）")
        due_entry = entry(right2, due_var)
        due_entry.pack(fill="x", ipady=7)
        tk.Checkbutton(
            body,
            text="加入今日清单",
            variable=today_var,
            bg=BG,
            fg=TEXT,
            activebackground=BG,
            font=(FONT, 9),
        ).pack(anchor="w", pady=12)

        def save() -> None:
            if not title_var.get().strip():
                messagebox.showwarning("缺少标题", "请填写任务标题。", parent=win)
                return
            self.selected_mainline_id = ids[line_var.get()]
            self.db.create_task(
                self.selected_mainline_id,
                title_var.get(),
                description.get("1.0", "end"),
                status_var.get(),
                priority_var.get(),
                due_var.get(),
                today_var.get(),
                next_action_var.get(),
            )
            win.destroy()
            self.show_view(self.current_view)

        button(body, "创建任务", save, primary=True).pack(anchor="e", pady=10)

    def open_thought_dialog(self) -> None:
        win, body = self.dialog("捕获灵感", "560x450")
        mainlines = self.db.list_mainlines()
        names = [row["name"] for row in mainlines]
        ids = {row["name"]: row["id"] for row in mainlines}
        current_name = next(
            (row["name"] for row in mainlines if row["id"] == self.selected_mainline_id), names[0]
        )
        title_var = tk.StringVar()
        line_var = tk.StringVar(value=current_name)
        self.form_label(body, "一句话灵感")
        title_entry = entry(body, title_var)
        title_entry.pack(fill="x", ipady=9)
        title_entry.focus_set()
        self.form_label(body, "原始内容（可选）")
        raw = text_box(body, height=5)
        raw.pack(fill="x")
        self.form_label(body, "先放在哪条主线")
        ttk.Combobox(body, values=names, textvariable=line_var, state="readonly").pack(fill="x")

        def save() -> None:
            if not title_var.get().strip():
                messagebox.showwarning("缺少灵感", "先写下一句话灵感。", parent=win)
                return
            self.selected_mainline_id = ids[line_var.get()]
            self.selected_thought_id = self.db.create_thought(
                title_var.get(), raw.get("1.0", "end"), self.selected_mainline_id
            )
            win.destroy()
            self.show_view("候审区" if self.current_view != "思路整理" else "思路整理")

        button(body, "放入候审区", save, primary=True).pack(anchor="e", pady=18)

    def open_task_detail(self, task_id: int) -> None:
        task = self.db.get_task(task_id)
        if not task:
            return
        win, body = self.dialog("任务详情", "590x690")
        tk.Label(body, text=task["mainline_name"], bg=BLUE_SOFT, fg=BLUE, padx=9, pady=4, font=(FONT, 8)).pack(anchor="w")
        title_var = tk.StringVar(value=task["title"])
        self.form_label(body, "任务标题")
        title = entry(body, title_var)
        title.pack(fill="x")
        self.form_label(body, "任务说明")
        description = text_box(body, task["description"], 4)
        description.pack(fill="x")
        self.form_label(body, "下一步")
        next_action_var = tk.StringVar(value=task["next_action"])
        next_action = entry(body, next_action_var)
        next_action.pack(fill="x")
        self.form_label(body, "状态")
        status_var = tk.StringVar(value=task["status"])
        ttk.Combobox(body, values=TASK_STATUSES, textvariable=status_var, state="readonly").pack(fill="x")
        today_var = tk.BooleanVar(value=bool(task["is_today"]))
        tk.Checkbutton(body, text="加入今日清单", variable=today_var, bg=BG, font=(FONT, 9)).pack(anchor="w", pady=15)
        linked = self.db.rows(
            """SELECT th.title, th.status FROM thoughts th
               JOIN thought_task_links l ON l.thought_id = th.id WHERE l.task_id = ?""",
            (task_id,),
        )
        self.form_label(body, "关联思路")
        tk.Label(body, text="、".join(row["title"] for row in linked) or "尚未关联思路", bg=BG, fg=MUTED, anchor="w", wraplength=480, font=(FONT, 9)).pack(fill="x")
        button(
            body,
            "MD 打开任务文档",
            lambda: self.open_markdown_editor("task", task_id),
        ).pack(anchor="w", pady=(18, 0))

        def save() -> None:
            if not title_var.get().strip():
                messagebox.showwarning("缺少标题", "请填写任务标题。", parent=win)
                return
            self.db.update_task(
                task_id,
                title=title_var.get(),
                description=description.get("1.0", "end"),
                next_action=next_action_var.get(),
            )
            self.db.update_task_status(task_id, status_var.get())
            self.db.set_task_today(task_id, today_var.get())
            win.destroy()
            self.show_view(self.current_view)

        button(body, "保存", save, primary=True).pack(anchor="e", pady=22)

    def open_log_dialog(self, thought_id: int) -> None:
        thought = self.db.get_thought(thought_id)
        if not thought:
            return
        win, body = self.dialog("记录本次执行", "650x750")
        tk.Label(body, text=thought["title"], bg=BG, fg=TEXT, font=(FONT, 12, "bold"), anchor="w").pack(fill="x", pady=(0, 8))
        boxes: dict[str, tk.Text] = {}
        for label, key, height in (
            ("本次行动", "action", 3),
            ("执行结果", "result", 3),
            ("遇到的阻碍", "blocker", 3),
            ("下一步", "next_step", 3),
        ):
            self.form_label(body, label)
            boxes[key] = text_box(body, thought["next_step"] if key == "action" else "", height)
            boxes[key].pack(fill="x")
        progress_var = tk.IntVar(value=thought["progress"])
        progress_row = tk.Frame(body, bg=BG)
        progress_row.pack(fill="x", pady=13)
        tk.Label(progress_row, text="执行进度", bg=BG, fg=TEXT, font=(FONT, 9, "bold")).pack(side="left")
        scale = tk.Scale(
            progress_row,
            from_=0,
            to=100,
            orient="horizontal",
            variable=progress_var,
            bg=BG,
            fg=MUTED,
            activebackground=BLUE,
            highlightthickness=0,
            troughcolor="#E8EBEF",
            length=330,
            font=(FONT, 8),
        )
        scale.pack(side="right")

        def save() -> None:
            action = boxes["action"].get("1.0", "end").strip()
            if not action:
                messagebox.showwarning("缺少行动", "请记录这次实际做了什么。", parent=win)
                return
            self.db.add_execution_log(
                thought_id,
                action=action,
                result=boxes["result"].get("1.0", "end"),
                blocker=boxes["blocker"].get("1.0", "end"),
                next_step=boxes["next_step"].get("1.0", "end"),
                progress=progress_var.get(),
            )
            win.destroy()
            self.selected_thought_id = thought_id
            self.show_view("思路整理" if self.current_view == "思路整理" else "执行区")

        button(body, "记录本次执行", save, primary=True).pack(anchor="e", pady=10)

    def generate_task(self, thought_id: int) -> None:
        task_id = self.db.create_task_from_thought(thought_id)
        task = self.db.get_task(task_id)
        messagebox.showinfo("任务已生成", f"已生成任务：{task['title']}", parent=self)
        self.show_view("思路整理")

    def open_link_task_dialog(self, thought_id: int) -> None:
        win, body = self.dialog("关联任务", "520x300")
        thought = self.db.get_thought(thought_id)
        tasks = self.db.list_tasks(thought["mainline_id"] if thought else self.selected_mainline_id)
        if not tasks:
            self.empty_state(body, "这条主线还没有任务", "请先新建任务。")
            return
        labels = [f"{row['status']} · {row['title']}" for row in tasks]
        ids = dict(zip(labels, (row["id"] for row in tasks)))
        value = tk.StringVar(value=labels[0])
        self.form_label(body, "选择要关联的任务")
        ttk.Combobox(body, values=labels, textvariable=value, state="readonly").pack(fill="x")

        def save() -> None:
            self.db.link_task(thought_id, ids[value.get()])
            win.destroy()
            self.show_view("思路整理")

        button(body, "添加关联", save, primary=True).pack(anchor="e", pady=24)

    def open_link_thought_dialog(self, thought_id: int) -> None:
        win, body = self.dialog("关联思路", "540x390")
        thoughts = [row for row in self.db.list_thoughts(self.selected_mainline_id) if row["id"] != thought_id]
        if not thoughts:
            self.empty_state(body, "没有其他思路", "捕获更多灵感后再建立关联。")
            return
        labels = [row["title"] for row in thoughts]
        ids = {row["title"]: row["id"] for row in thoughts}
        target_var = tk.StringVar(value=labels[0])
        relation_var = tk.StringVar(value="支撑")
        self.form_label(body, "选择另一条思路")
        ttk.Combobox(body, values=labels, textvariable=target_var, state="readonly").pack(fill="x")
        self.form_label(body, "关系类型（当前思路 → 另一条思路）")
        ttk.Combobox(body, values=RELATION_TYPES, textvariable=relation_var, state="readonly").pack(fill="x")
        tk.Label(body, text="支撑：提供依据；拆解：把问题拆小；启发：产生新方向；冲突：等待验证；延伸：形成后续。", bg=BG, fg=MUTED, wraplength=450, justify="left", font=(FONT, 8)).pack(anchor="w", pady=14)

        def save() -> None:
            self.db.link_thought(thought_id, ids[target_var.get()], relation_var.get())
            win.destroy()
            self.show_view("思路整理")

        button(body, "添加关联", save, primary=True).pack(anchor="e", pady=10)


def enable_high_dpi() -> None:
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def main() -> None:
    write_log("startup.log", f"Launch requested; Python={sys.executable}; cwd={Path.cwd()}")
    parser = argparse.ArgumentParser(description="ENTP 自强手册 2.0")
    parser.add_argument("--db", type=Path, default=Path(__file__).with_name("entp_manual.db"))
    parser.add_argument("--qa-screenshot", type=Path)
    parser.add_argument(
        "--qa-view",
        choices=("主线执行", "主线保管箱", "候审灵感", "今日记录", "历史日历", "思路整理"),
        default="主线执行",
    )
    parser.add_argument("--qa-day", help="Render one YYYY-MM-DD daily ledger during native QA")
    parser.add_argument("--qa-size", help="Set a native QA viewport such as 1180x720")
    parser.add_argument("--qa-markdown", help="Open KIND:ID in the Markdown editor for native QA")
    args = parser.parse_args()
    enable_high_dpi()
    app = ENTPManualApp(args.db)
    if args.qa_size:
        app.geometry(args.qa_size)
    if args.qa_day:
        app.selected_day = date.fromisoformat(args.qa_day)
    capture_target: tk.Misc = app
    if args.qa_markdown:
        kind, raw_id = args.qa_markdown.split(":", 1)
        editor = app.open_markdown_editor(kind, int(raw_id))
        if editor is not None:
            capture_target = editor
    if args.qa_screenshot:
        def capture() -> None:
            from PIL import ImageGrab

            capture_target.winfo_toplevel().deiconify()
            capture_target.winfo_toplevel().lift()
            capture_target.winfo_toplevel().attributes("-topmost", True)
            capture_target.winfo_toplevel().focus_force()
            capture_target.winfo_toplevel().update()
            args.qa_screenshot.parent.mkdir(parents=True, exist_ok=True)
            ImageGrab.grab(window=capture_target.winfo_id()).save(args.qa_screenshot)
            app.after(200, app.on_close)

        if not args.qa_markdown:
            app.show_view(args.qa_view)
            if args.qa_view in ("主线执行", "历史日历"):
                def prepare_capture_state() -> None:
                    app.calendar_selected_day = date.today()
                    app.calendar_month = date.today().replace(day=1)
                    app.show_view(args.qa_view)

                app.after(800, prepare_capture_state)
        app.after(1600, capture)
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        details = traceback.format_exc()
        write_log("crash.log", "Fatal startup error\n" + details)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "ENTP 自强手册启动失败",
                f"详细错误已保存到：\n{LOG_DIR / 'crash.log'}",
            )
            root.destroy()
        except Exception:
            pass
        raise
