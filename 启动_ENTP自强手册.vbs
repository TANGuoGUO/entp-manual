Option Explicit

Dim fso, shell, appDir, pythonw, command, argument
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = appDir & "\.venv\Scripts\pythonw.exe"

If Not fso.FileExists(appDir & "\launcher_flet.pyw") Then
    MsgBox "launcher_flet.pyw was not found in:" & vbCrLf & appDir, vbCritical, "ENTP Manual 2.0"
    WScript.Quit 2
End If

If Not fso.FileExists(pythonw) Then
    MsgBox "Flet 运行环境不存在。请先执行 requirements-flet.txt 的安装步骤。", vbCritical, "ENTP 自强手册 2.0"
    WScript.Quit 3
End If

command = Quote(pythonw) & " " & Quote(appDir & "\launcher_flet.pyw")

For Each argument In WScript.Arguments
    command = command & " " & Quote(argument)
Next

shell.CurrentDirectory = appDir
shell.Run command, 0, False

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
