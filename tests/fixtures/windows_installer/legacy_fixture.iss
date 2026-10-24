; 固定官方旧 ZIP 的测试专用封装；此文件不是历史发布安装器，也不接受版本覆盖。
#ifdef AppVersion
  #error The legacy fixture version cannot be overridden
#endif
#define AppVersion "3.3.2"
#include ProtocolInclude
[Setup]
AppId={{#InstallAppId}
AppName=ADBLab
AppVersion=3.3.2
AppVerName=ADBLab 3.3.2 legacy ZIP test wrapper
DefaultDirName={localappdata}\Programs\ADBLab
DefaultGroupName=ADBLab
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=legacy-zip-v3.3.2-test-setup
Compression=lzma2
SolidCompression=yes
CloseApplications=no
RestartApplications=no
UninstallLogMode=append
UninstallDisplayIcon={app}\{#MainExecutable}

[Files]
Source: "{#AppSourceDir}\{#InstallManifest}"; Flags: dontcopy
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Excludes: "{#InstallManifest}"; Flags: ignoreversion recursesubdirs createallsubdirs uninsneveruninstall

[Icons]
Name: "{userprograms}\ADBLab\ADBLab"; Filename: "{app}\{#MainExecutable}"; WorkingDir: "{app}"

[Code]
#include "..\..\..\scripts\windows_installer\maintenance.iss"
