# Windows 安装版

发布文件：`release/ENTP自强手册_2.0.0_安装版.exe`

安装向导提供以下可选任务：

- 创建桌面快捷方式（默认不勾选）。
- 登录 Windows 后自动启动（使用任务计划程序，默认不勾选）。

计划任务名称为 `ENTPManual_Autostart`，触发方式为当前用户登录 Windows，运行权限为 `LIMITED`。安装阶段需要一次 UAC 管理员确认；程序日常运行不需要管理员权限。取消勾选自动启动后重新安装/升级会删除旧任务，卸载程序也会删除该任务。

安装后的用户数据不会写入安装目录，而是保存在：

```text
%LOCALAPPDATA%\ENTP自强手册
```

该目录包含 SQLite 数据库、Markdown、日志和导入前备份。卸载程序默认保留用户数据，避免误删记录。

## 重新构建

需要 Python 3.12、项目虚拟环境、PyInstaller 6.22 和 Inno Setup 6：

```powershell
cd G:\project\entp
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\installer\build_installer.ps1
```

安装脚本位于 `installer/entp_installer.iss`。构建结果默认不纳入 Git，由本地 `release/` 目录交付。
