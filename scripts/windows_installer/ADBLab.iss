; 编译入口只消费经过验证的 staging，协议常量由 Python 单一来源生成。
#ifndef AppSourceDir
  #error AppSourceDir is required
#endif
#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef ProtocolInclude
  #error ProtocolInclude is required
#endif
#include ProtocolInclude

[Setup]
AppId={{#InstallAppId}
AppName=ADBLab
AppVersion={#AppVersion}
AppVerName=ADBLab {#AppVersion}
DefaultDirName={localappdata}\Programs\ADBLab
DefaultGroupName=ADBLab
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=ADBLab-win-x64-v{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
CloseApplications=no
RestartApplications=no
RestartIfNeededByRun=no
AllowNoIcons=no
UninstallDisplayIcon={app}\{#MainExecutable}
UninstallLogMode=append
WizardStyle=modern

[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
Source: "{#AppSourceDir}\{#InstallManifest}"; Flags: dontcopy
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Excludes: "{#InstallManifest}"; Flags: ignoreversion recursesubdirs createallsubdirs uninsneveruninstall

[Icons]
Name: "{userprograms}\ADBLab\ADBLab"; Filename: "{app}\{#MainExecutable}"; WorkingDir: "{app}"
Name: "{userdesktop}\ADBLab"; Filename: "{app}\{#MainExecutable}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MainExecutable}"; Description: "启动 ADBLab"; Flags: nowait postinstall skipifsilent; Check: CanLaunch; BeforeInstall: ReleaseMaintenanceLock

[Code]
#include "maintenance.iss"
