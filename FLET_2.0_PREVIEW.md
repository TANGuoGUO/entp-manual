# ENTP 自强手册 2.0（Flet 预览）

双击 `启动_ENTP自强手册_2.0预览.vbs` 启动新版界面。原来的 Tkinter 启动入口与代码均保留，可随时回退。

当前阶段已经迁移：

- 单层框架导航，不再同时显示重复的左右竖栏。
- “当前主线”专注执行页：焦点任务、最小下一步、执行记录、任务完成与月历沉淀。
- “我的主线任务保管箱”：隐藏其他主线，直接设为当前主线，查看各自主线任务。
- Flet 原生卡片、按钮、勾选框、对话框、导航、动画和响应式布局。
- 任务操作只更新任务区、进度和日历，不再清空并重建整个窗口。
- 继续复用 `database.py`、`entp_manual.db`、`markdown_store.py` 和原有 Markdown 文档。

候审区、今日清单和独立完成日历目前保留导航位置，下一阶段逐页迁移；旧版中的对应功能仍然可用。

如需在另一台电脑安装依赖：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-flet.txt
```
