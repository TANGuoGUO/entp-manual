Option Explicit

Dim shell, fso, projectDir, pythonw, launcher
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = projectDir & "\.venv\Scripts\pythonw.exe"
launcher = projectDir & "\launcher_flet.pyw"

If Not fso.FileExists(pythonw) Then
    MsgBox "Flet 运行环境尚未安装。请先运行项目中的安装步骤。", 16, "ENTP 自强手册 2.0"
    WScript.Quit 1
End If

shell.CurrentDirectory = projectDir
shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & launcher & Chr(34), 0, False
