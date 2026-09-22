; ============================================================================
;  AI Studio · AI 漫剧工厂 —— Windows 安装包脚本（Inno Setup 6+）
;
;  前置：先执行  python build_exe.py  生成 dist\AIVerse.exe
;  编译：iscc installer\aiverse.iss     （或右键用 Inno Setup Compiler 打开）
;  产物：installer\Output\AIVerse-Setup-1.0.4.exe
;
;  说明：默认安装到 %LOCALAPPDATA%\Programs\AI Studio，
;        无需管理员权限，且用户数据目录可写。
;        卸载时**不会**删除用户项目数据。
;
;  关于体积（重要，别改错）：
;    本安装包只包含「编排大脑」——剧本/角色/分镜/审核/抽卡/剪辑 + 一键部署器，
;    约 10 MB。真正出片的算力是 MiniMax H3（33B 参数，精简版权重 39 GB 起），
;    物理上不可能塞进安装包。所以安装完会引导用户点一下「一键部署」，
;    自动装好 Python/PyTorch/ComfyUI/H3 权重/FFmpeg；也可以走「离线包导入」，
;    在别的机器上零下载复制过去。
; ============================================================================

#define MyAppName "AI Studio"
#define MyAppNameCN "AI 漫剧工厂"
#define MyAppVersion "1.0.4"
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
Name: "deployshortcut"; Description: "创建「一键部署本地推理环境」快捷方式（推荐）"; GroupDescription: "附加任务："
Name: "autostart"; Description: "安装完成后立即启动 {#MyAppName}"; GroupDescription: "附加任务："; Flags: checkedonce

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

; 安装版标记：客户端读到它就会把「项目数据 + 30GB 运行时」放到
; %LOCALAPPDATA%\AIVerse，而不是安装目录里。绿色版（直接拷 exe）没有这个文件，
; 会全部放在 exe 同级，可随 U 盘带走。
[INI]
Filename: "{app}\aiverse.ini"; Section: "install"; Key: "installed"; String: "1"
Filename: "{app}\aiverse.ini"; Section: "install"; Key: "data_root"; String: "{localappdata}\AIVerse"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\一键部署本地推理环境"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--setup"
Name: "{group}\{#MyAppNameCN} 使用说明"; Filename: "{app}\README.md"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{autodesktop}\一键部署本地推理环境"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--setup"; Tasks: deployshortcut

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent; Tasks: autostart

[UninstallRun]
; 不自动删除任何用户数据

; 实测发现：卸载后 {app}\aiverse.ini 会残留（Inno 对 [INI] 的自动清理不可靠），
; 结果用户卸载完还会看到一个装着 80 字节 ini 的空目录。显式清掉。
; 注意只清安装目录里的东西 —— %LOCALAPPDATA%\AIVerse 下的项目数据与 30GB 运行时
; 是刻意保留的，重装后可直接复用。
[UninstallDelete]
Type: files; Name: "{app}\aiverse.ini"
Type: dirifempty; Name: "{app}"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  DataDir: String;
begin
  if (CurStep = ssPostInstall) and (not WizardSilent) then
  begin
    DataDir := ExpandConstant('{localappdata}\AIVerse');
    MsgBox('安装完成。' + #13#10 + #13#10 +
           '关于体积，先说清楚（避免误会）：' + #13#10 +
           '  · 本安装包约 10 MB，它是「编排大脑」——剧本、角色、分镜、' + #13#10 +
           '    审核门、抽卡、局部重生成、剪辑导出，外加一键部署器。' + #13#10 +
           '  · 真正出片的算力是 MiniMax H3（33B 参数），精简版权重 39 GB 起，' + #13#10 +
           '    加 PyTorch/CUDA 共约 30 GB。没有任何软件能把它塞进 10 MB。' + #13#10 + #13#10 +
           '所以下一步请点「一键部署本地推理环境」（桌面或开始菜单里都有），' + #13#10 +
           '它会全自动装好一切；如果你的机器不方便联网，' + #13#10 +
           '也可以在「环境部署」页用「离线包导入」，从 U 盘零下载复制。' + #13#10 + #13#10 +
           '运行时目录：' + DataDir + '\runtime', mbInformation, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
  begin
    DataDir := ExpandConstant('{localappdata}\AIVerse');
    if DirExists(DataDir) then
      MsgBox('你的项目数据与本地推理运行时仍保留在：' + #13#10 + DataDir + #13#10 + #13#10 +
             '（重装后可直接复用，无需重新下载 30 GB 的模型）' + #13#10 +
             '如需彻底清理，请手动删除该目录。', mbInformation, MB_OK);
  end;
end;

