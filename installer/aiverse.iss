; ============================================================================
;  AI Studio · AI 漫剧工厂 —— Windows 安装包脚本（Inno Setup 6+）
;
;  前置：先执行  python build_exe.py  生成 dist\AIVerse.exe
;  编译：iscc installer\aiverse.iss     （或右键用 Inno Setup Compiler 打开）
;  产物：installer\Output\AIVerse-Setup-1.0.0.exe
;
;  说明：默认安装到 %LOCALAPPDATA%\Programs\AI Studio，
;        无需管理员权限，且用户数据目录可写。
;        卸载时**不会**删除用户项目数据。
; ============================================================================

#define MyAppName "AI Studio"
#define MyAppNameCN "AI 漫剧工厂"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "AIVerse"
#define MyAppExeName "AIVerse.exe"

[Setup]
AppId={{7C4E1B92-5A3D-4F18-9E6C-2D8B0A5F3C71}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion} ({#MyAppNameCN})
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\AI Studio
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=AIVerse-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\aiverse.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableDirPage=auto
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppNameCN} 使用说明"; Filename: "{app}\README.md"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 不自动删除任何用户数据

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{app}\projects');
    if DirExists(DataDir) then
      MsgBox('你的项目数据仍保留在：' + #13#10 + DataDir + #13#10 + #13#10 +
             '如需彻底清理，请手动删除该目录。', mbInformation, MB_OK);
  end;
end;
