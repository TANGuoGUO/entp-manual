#define MyAppName "ENTP 自强手册"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "ENTP Manual"
#define MyAppExeName "ENTPManual.exe"
#define MyTaskName "ENTPManual_Autostart"

[Setup]
AppId={{F5E43EE6-9742-4B20-910B-38FC50C21655}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ENTP自强手册
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=..\release
OutputBaseFilename=ENTP自强手册_2.0.0_安装版
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked
Name: "autostart"; Description: "登录 Windows 后自动启动（使用任务计划程序）"; GroupDescription: "自动启动："; Flags: unchecked

[Files]
Source: "..\release\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /F /TN ""{#MyTaskName}"""; Flags: runhidden waituntilterminated; RunOnceId: "DeleteEntpAutostartTask"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('autostart') then
    begin
      if (not Exec(
        ExpandConstant('{sys}\schtasks.exe'),
        ExpandConstant('/Create /F /TN "{#MyTaskName}" /SC ONLOGON /TR "{app}\{#MyAppExeName}" /RL LIMITED'),
        '', SW_HIDE, ewWaitUntilTerminated, ResultCode
      )) or (ResultCode <> 0) then
      begin
        Log(Format('Failed to create autostart task. Exit code: %d', [ResultCode]));
        MsgBox('程序已经安装成功，但登录后自动启动任务创建失败。你仍然可以从开始菜单手动启动程序。', mbError, MB_OK);
      end;
    end
    else
      Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /F /TN "{#MyTaskName}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
end;
