#define MyAppName "ENTP 自强手册"
#define MyAppVersion "2.1.4"
#define MyAppPublisher "ENTP Manual"
#define MyAppExeName "ENTPManual.exe"
#define MyTaskName "ENTPManual_Autostart"
#ifndef AppBundleDir
#define AppBundleDir "..\build\windows"
#endif

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
OutputBaseFilename=ENTP-Manual-2.1.4-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\app-icon.ico
SetupLogging=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UsePreviousTasks=yes

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked
Name: "autostart"; Description: "登录 Windows 后在后台启动（隐藏任务栏图标，使用任务计划程序）"; GroupDescription: "自动启动："; Flags: unchecked

[Files]
Source: "{#AppBundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\assets\app-icon.ico"; DestDir: "{app}"; DestName: "ENTPManual.ico"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\ENTPManual.ico"; IconIndex: 0
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"; Comment: "卸载程序（默认保留个人数据）"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\ENTPManual.ico"; IconIndex: 0; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Parameters: "--updated"; Flags: nowait skipifnotsilent

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /F /TN ""{#MyTaskName}"""; Flags: runhidden waituntilterminated; RunOnceId: "DeleteEntpAutostartTask"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function XmlEscape(Value: String): String;
begin
  StringChangeEx(Value, '&', '&amp;', True);
  StringChangeEx(Value, '<', '&lt;', True);
  StringChangeEx(Value, '>', '&gt;', True);
  StringChangeEx(Value, '"', '&quot;', True);
  StringChangeEx(Value, '''', '&apos;', True);
  Result := Value;
end;

function CreateAutostartTask(var ResultCode: Integer): Boolean;
var
  DomainName: String;
  UserName: String;
  UserId: String;
  ExePath: String;
  XmlPath: String;
  TaskXml: String;
begin
  DomainName := GetEnv('USERDOMAIN');
  UserName := GetEnv('USERNAME');
  if DomainName <> '' then
    UserId := DomainName + '\' + UserName
  else
    UserId := UserName;

  ExePath := ExpandConstant('{app}\{#MyAppExeName}');
  XmlPath := ExpandConstant('{tmp}\ENTPManual_Autostart.xml');
  TaskXml :=
    '<?xml version="1.0" encoding="UTF-8"?>' + #13#10 +
    '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">' + #13#10 +
    '  <RegistrationInfo><Description>Start ENTP Manual hidden after Windows logon.</Description></RegistrationInfo>' + #13#10 +
    '  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>' + XmlEscape(UserId) + '</UserId></LogonTrigger></Triggers>' + #13#10 +
    '  <Principals><Principal id="Author"><UserId>' + XmlEscape(UserId) + '</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>' + #13#10 +
    '  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings><AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Priority>7</Priority></Settings>' + #13#10 +
    '  <Actions Context="Author"><Exec><Command>' + XmlEscape(ExePath) + '</Command><Arguments>--start-hidden</Arguments></Exec></Actions>' + #13#10 +
    '</Task>' + #13#10;

  if not SaveStringToFile(XmlPath, UTF8Encode(TaskXml), False) then
  begin
    ResultCode := -1;
    Result := False;
    Exit;
  end;

  Result := Exec(
    ExpandConstant('{sys}\schtasks.exe'),
    '/Create /F /TN "{#MyTaskName}" /XML "' + XmlPath + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode
  );
  DeleteFile(XmlPath);
  Result := Result and (ResultCode = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('autostart') then
    begin
      if not CreateAutostartTask(ResultCode) then
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
