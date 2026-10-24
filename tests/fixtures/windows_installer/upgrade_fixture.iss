; 独立 CI 测试产品复用生产维护模块，不提供修改正式产品身份的测试开关。
#include ProtocolInclude
[Setup]
AppId={{#InstallAppId}
AppName=ADBLab upgrade fixture
AppVersion={#AppVersion}
DefaultDirName={tmp}\ADBLab-upgrade-fixture-unused
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=upgrade-fixture-{#AppVersion}
Compression=lzma2
SolidCompression=yes
CloseApplications=no
RestartApplications=no
UninstallLogMode=append
UninstallDisplayName=ADBLab upgrade fixture {#AppVersion}

[Files]
Source: "{#AppSourceDir}\{#InstallManifest}"; Flags: dontcopy
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Excludes: "{#InstallManifest}"; Flags: ignoreversion recursesubdirs createallsubdirs uninsneveruninstall

[Code]
#include "..\..\..\scripts\windows_installer\maintenance.iss"
