; 仅 CI 一次性 fixture 消费故障宏；正式构建入口明确拒绝这些定义。
#define ADBLAB_TEST_FAULTS
#include ProtocolInclude
[Setup]
AppId={{#InstallAppId}
AppName=ADBLab fault fixture
AppVersion={#AppVersion}
DefaultDirName={tmp}\ADBLab-fault-fixture-unused
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=fault-fixture
Compression=lzma2
SolidCompression=yes
CloseApplications=no
RestartApplications=no
UninstallLogMode=append
UninstallDisplayName=ADBLab fault fixture {#AppVersion}

[Files]
Source: "{#AppSourceDir}\{#InstallManifest}"; Flags: dontcopy
; 主程序先复制，提供真正的部分载荷安装边界；fixture 不启动这些合成字节。
Source: "{#AppSourceDir}\{#MainExecutable}"; DestDir: "{app}"; Flags: ignoreversion uninsneveruninstall; AfterInstall: InstallerTestPayloadCopied
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Excludes: "{#InstallManifest},{#MainExecutable}"; Flags: ignoreversion recursesubdirs createallsubdirs uninsneveruninstall

[Code]
#include "..\..\..\scripts\windows_installer\maintenance.iss"
