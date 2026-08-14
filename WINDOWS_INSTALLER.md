# Windows 安装版

发布文件：`release/ENTP自强手册_2.1.0_初始化版.exe`

安装向导提供以下可选任务：

- 创建桌面快捷方式（默认不勾选）。
- 登录 Windows 后在后台启动（隐藏任务栏图标，使用任务计划程序，默认不勾选）。

计划任务名称为 `ENTPManual_Autostart`，触发方式为当前用户登录 Windows，运行权限为 `LIMITED`，启动参数为 `--start-hidden`。安装阶段需要一次 UAC 管理员确认；程序日常运行不需要管理员权限。取消勾选自动启动后重新安装/升级会删除旧任务，卸载程序也会删除该任务。

程序运行时可点击左下角“隐藏到托盘”，或者直接关闭窗口。此时窗口和任务栏图标都会隐藏，但程序继续在后台运行。双击系统托盘图标可以恢复窗口；托盘菜单中的“退出”才会真正结束程序。

## GitHub 一键更新

2.1.0 起，程序左下角提供“检查更新”。程序每天最多自动检查一次 GitHub Releases；自动检查失败不会打断正常使用。发现正式版后，可以在程序内下载、校验 SHA-256，并静默覆盖旧版本。安装完成后程序会自动重新启动。

更新只替换安装目录中的程序文件，不会修改 `%LOCALAPPDATA%\ENTP自强手册` 内的数据库、Markdown、日志或备份。已有的桌面快捷方式和登录后后台启动选择会沿用上一次安装设置。

## 卸载

安装后可以使用任意一种入口：

- 开始菜单 → `ENTP 自强手册` → `卸载 ENTP 自强手册`。
- Windows 设置 → 应用 → 已安装的应用 → `ENTP 自强手册` → 卸载。
- 安装目录中的 `unins000.exe`。

卸载器会移除程序文件、快捷方式和 `ENTPManual_Autostart` 定时任务。个人数据库与 Markdown 默认保留在 `%LOCALAPPDATA%\ENTP自强手册`，避免误删；如果确认不再需要记录，可以在卸载完成后手动删除该目录。

安装后的用户数据不会写入安装目录，而是保存在：

```text
%LOCALAPPDATA%\ENTP自强手册
```

该目录包含 SQLite 数据库、Markdown、日志和导入前备份。卸载程序默认保留用户数据，避免误删记录。

全新数据库第一次启动会写入一次性的功能导览工作区。所有初始主线、任务、灵感、今日条目和日历完成记录都用于介绍软件本身，并且都是可编辑的普通数据。已有数据库不会补写、重置或覆盖这些内容。

## 重新构建

需要 Python 3.12、项目虚拟环境、PyInstaller 6.22 和 Inno Setup 6：

```powershell
cd G:\project\entp
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\installer\build_installer.ps1
```

安装脚本位于 `installer/entp_installer.iss`。构建结果默认不纳入 Git，由本地 `release/` 目录交付。
