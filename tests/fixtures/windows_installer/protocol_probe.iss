; 此独立探针只在 InitializeSetup 验证协议并返回 False，从不执行安装或修改注册表。
#include ProtocolInclude
#define AppVersion "1.0.0"
[Setup]
AppName=ADBLab protocol probe
AppVersion=1.0.0
AppId=ADBLabProtocolProbe
DefaultDirName={tmp}\ADBLabProtocolProbeUnused
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
OutputBaseFilename=protocol-probe
CloseApplications=no

[Code]
#include "..\..\..\scripts\windows_installer\maintenance.iss"

procedure ExpectInvalidPath(Value: String);
begin
  Require(not ValidRelativePath(Value), 'unsafe path accepted: ' + Value);
end;

procedure WriteFixtureManifest(Path, Content: String);
var Lines: TArrayOfString;
begin
  SetArrayLength(Lines, 1);
  Lines[0] := GetSHA256OfString(Content) + #9 + 'ADBLab.exe';
  Require(SaveStringsToUTF8File(Path, Lines, False), 'fixture write failed');
end;

procedure WriteProbeReport(Path, Content: String);
var Lines: TArrayOfString;
begin
  SetArrayLength(Lines, 1);
  Lines[0] := Content;
  Require(SaveStringsToUTF8FileWithoutBOM(Path, Lines, False), 'cannot write probe result');
end;

procedure ExpectProtectedRoot(Path: String);
var OriginalRoot, Failure: String;
begin
  OriginalRoot := RootDir;
  RootDir := Path;
  Failure := '';
  try
    try CheckRootDirectory; except Failure := GetExceptionMessage; end;
    Require(Failure = '安装目录不能覆盖系统目录、用户数据或导出目录。',
      'protected path did not reach the intended containment check: ' + Failure);
  finally
    RootDir := OriginalRoot;
  end;
end;

procedure ExerciseUpgradeOwnership;
var
  OriginalRoot, AHash, BHash: String;
  Lines: TArrayOfString;
  BusyHandle, RunningHandle: LongWord;
  Failed: Boolean;
  I: Integer;
begin
  OriginalRoot := RootDir;
  RootDir := AddBackslash(RootDir) + 'upgrade-ownership';
  Require(ForceDirectories(RootDir), 'upgrade fixture root');
  AcquireMaintenanceLock(True);
  SetArrayLength(Lines, 3);
  Lines[0] := GetSHA256OfString('A') + #9 + 'ADBLab.exe';
  Lines[1] := GetSHA256OfString('retired A') + #9 + 'retired.dat';
  Lines[2] := GetSHA256OfString('tool A') + #9 + 'adb.exe';
  Require(SaveStringsToUTF8File(ControlPath(ManifestName), Lines, False), 'write A manifest');
  AHash := GetSHA256OfFile(ControlPath(ManifestName));
  SetArrayLength(Lines, 2);
  Lines[0] := GetSHA256OfString('B') + #9 + 'ADBLab.exe';
  Lines[1] := GetSHA256OfString('tool B') + #9 + 'adb.exe';
  Require(SaveStringsToUTF8File(ControlPath(PendingName), Lines, False), 'write B manifest');
  BHash := GetSHA256OfFile(ControlPath(PendingName));
  Require(SaveStringToFile(ManagedPath('ADBLab.exe'), 'A', False), 'write A');
  Require(SaveStringToFile(ManagedPath('retired.dat'), 'retired A', False), 'write retired');
  Require(SaveStringToFile(ManagedPath('adb.exe'), 'tool A', False), 'write tool');
  PublishIdentity('installing', '0.9.0', '1.0.0', AHash, BHash);
  LoadIdentity;
  TargetFiles := PendingFiles;
  PreflightInstall;
  BusyHandle := WinCreateFile(ManagedPath('adb.exe'), GenericRead, 1, 0, OpenExisting, FileNormal, 0);
  Require(BusyHandle <> $FFFFFFFF, 'cannot simulate busy independent tool');
  try
    Failed := False;
    try PreflightInstall; except Failed := True; end;
    Require(Failed, 'independent tool handle did not block upgrade preflight');
    Require(GetSHA256OfFile(ManagedPath('ADBLab.exe')) = GetSHA256OfString('A'), 'failed preflight changed old payload');
    Require(FileExists(ManagedPath('retired.dat')), 'failed preflight deleted retired payload');
  finally
    WinCloseHandle(BusyHandle);
  end;
  ReleaseMaintenanceLock;
  RunningHandle := WinCreateFile(ControlPath(LockName), GenericRead, 1, 0, OpenExisting, FileNormal, 0);
  Require(RunningHandle <> $FFFFFFFF, 'cannot simulate running application');
  try
    Failed := False;
    try AcquireMaintenanceLock(False); except Failed := True; end;
    Require(Failed and not HasMaintenanceLock, 'running application did not block maintenance');
  finally
    WinCloseHandle(RunningHandle);
  end;
  AcquireMaintenanceLock(False);
  Require(SaveStringToFile(ManagedPath('ADBLab.exe'), 'B', False), 'write B');
  RunningHandle := WinCreateFile(ControlPath(LockName), GenericRead, 1, 0, OpenExisting, FileNormal, 0);
  Require(RunningHandle = $FFFFFFFF, 'application entry admitted during partial upgrade');
  Require(SaveStringToFile(ManagedPath('adb.exe'), 'tool B', False), 'write B tool');
  DeleteManaged(ManagedPath('retired.dat'), GetSHA256OfString('retired A'), '');
  Require(not FileExists(ManagedPath('retired.dat')), 'retired A file was not removed');
  PublishManifest(ControlPath(ManifestName), PreviousName);
  PublishManifest(ControlPath(PendingName), ManifestName);
  PublishIdentity('ready', '1.0.0', '', BHash, '');
  Require(DeleteFile(ControlPath(PendingName)), 'cleanup B pending');
  Require(DeleteFile(ControlPath(PreviousName)), 'cleanup A journal');
  LoadIdentity;
  Failed := False;
  try RequireRecoveryTarget('0.9.0', AHash); except Failed := True; end;
  Require(Failed, 'completed B accepted downgrade to old A');
  Require(SaveStringToFile(ManagedPath('retired.dat'), 'user replacement', False), 'write replacement at retired path');
  Require(SaveStringToFile(ManagedPath('personal.dat'), 'user extra', False), 'write unknown file');
  CheckManagedFiles(CurrentFiles, True);
  PublishIdentity('removing', CompletedVersion, '', CompletedDigest, '');
  for I := 0 to GetArrayLength(CurrentFiles) - 1 do
    DeleteManaged(ManagedPath(CurrentFiles[I].RelativePath), CurrentFiles[I].Digest, '');
  Require(GetSHA256OfFile(ManagedPath('retired.dat')) = GetSHA256OfString('user replacement'), 'retired-path user file deleted');
  Require(GetSHA256OfFile(ManagedPath('personal.dat')) = GetSHA256OfString('user extra'), 'unknown user file deleted');
  LoadIdentity;
  CheckManagedFiles(CurrentFiles, True);
  ReleaseMaintenanceLock;
  RootDir := OriginalRoot;
end;

function InitializeSetup: Boolean;
var
  Output, AHash, BHash, Failure: String;
  Failed: Boolean;
  Files: TManagedFiles;
  Handle: LongWord;
begin
  Result := False;
  Output := '{#ProbeOutput}';
  try
    Require(ValidRelativePath('_internal/中文 file.dll'), 'unicode path rejected');
    ExpectInvalidPath('../bad'); ExpectInvalidPath('/bad'); ExpectInvalidPath('C:/bad');
    ExpectInvalidPath('a\b'); ExpectInvalidPath('x:ads'); ExpectInvalidPath('a//b');
    ExpectInvalidPath('a/../b'); ExpectInvalidPath('a.'); ExpectInvalidPath('a ');
    ExpectInvalidPath('CON'); ExpectInvalidPath('nul.txt'); ExpectInvalidPath('.adblab-install.ini');
    ExpectInvalidPath('unins000.exe'); ExpectInvalidPath('a' + #9 + 'b');
    Require(CompareVersions('1.10.0', '1.9.9') = 1, 'version numeric ordering');
    Require(CompareVersions('1.0.0', '1.0.0') = 0, 'repair version');
    Require(CompareVersions('1.0.0', '2.0.0') = -1, 'downgrade ordering');
    RootDir := '{#ProbeRoot}';
    if {#ProbeInvalidHome} = 1 then begin
      Failure := '';
      try ProcessHomeDirectory; except Failure := GetExceptionMessage; end;
      Require(Failure = '进程用户目录不是完整绝对路径，请检查用户环境。', 'invalid process home accepted: ' + Failure);
      WriteProbeReport(Output, 'PASS');
      Exit;
    end;
    // 普通临时子目录必须通过完整准入，不能把任意 API 异常当成危险目录拒绝。
    CheckRootDirectory;
    Require(NormalPath(CurrentProfileDirectory) = NormalPath('{#ProbeExpectedProfile}'), 'Shell profile mismatch');
    Require(NormalPath(ProcessHomeDirectory) = NormalPath('{#ProbeExpectedHome}'), 'Python home boundary mismatch');
    ExpectProtectedRoot(ExpandConstant('{localappdata}\ADBLab'));
    ExpectProtectedRoot(AddBackslash(CurrentProfileDirectory) + 'ADBLab');
    ExpectProtectedRoot(CurrentProfileDirectory);
    ExpectProtectedRoot(AddBackslash(CurrentProfileDirectory) + 'ADBLab\child');
    ExpectProtectedRoot(AddBackslash(ProcessHomeDirectory) + 'ADBLab');
    ExpectProtectedRoot(ExpandConstant('{win}'));
    ExpectProtectedRoot(ExpandConstant('{pf}'));
    Require(ExpandConstant('{userprograms}') <> '', 'userprograms constant unavailable');
    Require(ExpandConstant('{userdesktop}') <> '', 'userdesktop constant unavailable');
    Require(ForceDirectories(RootDir), 'fixture root');
    AcquireMaintenanceLock(True);
    Handle := WinCreateFile(ControlPath(LockName), GenericRead, 1, 0, OpenExisting, FileNormal, 0);
    Require(Handle = $FFFFFFFF, 'exclusive lock did not exclude readers');
    WriteFixtureManifest(ControlPath(ManifestName), 'A');
    AHash := GetSHA256OfFile(ControlPath(ManifestName));
    WriteFixtureManifest(ControlPath(PendingName), 'B');
    BHash := GetSHA256OfFile(ControlPath(PendingName));
    PublishIdentity('installing', '0.9.0', '1.0.0', AHash, BHash);
    LoadIdentity;
    Require((CompletedVersion = '0.9.0') and (PendingVersion = '1.0.0'), 'identity roundtrip');
    RequireRecoveryTarget('1.0.0', BHash);
    Failed := False;
    try RequireRecoveryTarget('1.1.0', BHash); except Failed := True; end;
    Require(Failed, 'A to B interruption accepted C');
    Failed := False;
    try RequireRecoveryTarget('1.0.0', AHash); except Failed := True; end;
    Require(Failed, 'same version changed payload accepted');
    Require(SaveStringToFile(ManagedPath('ADBLab.exe'), 'A', False), 'write old payload');
    CheckManagedFiles(CurrentFiles, True);
    CheckManagedFiles(PendingFiles, True);
    Require(SaveStringToFile(ManagedPath('ADBLab.exe'), 'B', False), 'write pending payload');
    CheckManagedFiles(CurrentFiles, True);
    CheckManagedFiles(PendingFiles, True);
    Require(SaveStringToFile(ManagedPath('ADBLab.exe'), 'user', False), 'write modified payload');
    Failed := False;
    try CheckManagedFiles(CurrentFiles, True); except Failed := True; end;
    Require(Failed, 'modified owned file accepted for delete');
    ReadManifest(ControlPath(ManifestName), AHash, Files);
    Require(GetArrayLength(Files) = 1, 'manifest read');
    Require(GetSHA256OfString('A') = Files[0].Digest, 'manifest content');
    PublishManifest(ControlPath(ManifestName), PreviousName);
    PublishManifest(ControlPath(PendingName), ManifestName);
    LoadIdentity;
    Require(CurrentFiles[0].Digest = GetSHA256OfString('A'), 'commit-window lost old ownership');
    Require(PendingFiles[0].Digest = GetSHA256OfString('B'), 'commit-window lost pending ownership');
    PublishIdentity('ready', '1.0.0', '', BHash, '');
    LoadIdentity;
    Require(OldState = 'ready', 'ready leftover pending not accepted');
    DeleteIniEntry(SectionName, 'PendingVersion', ControlPath(MarkerName));
    Failed := False;
    try LoadIdentity; except Failed := True; end;
    Require(Failed, 'missing empty identity field accepted');
    PublishIdentity('ready', '1.0.0', '', BHash, '');
    LoadIdentity;
    RequireRecoveryTarget('1.1.0', AHash);
    Failed := False;
    try RequireRecoveryTarget('0.9.0', AHash); except Failed := True; end;
    Require(Failed, 'downgrade accepted');
    PublishIdentity('removing', '1.0.0', '', BHash, '');
    LoadIdentity;
    Require((OldState = 'removing') and FileExists(ControlPath(PendingName)), 'removing lost ready leftover ownership');
    WriteFixtureManifest(ControlPath(PendingName), 'A');
    Failed := False;
    try LoadIdentity; except Failed := True; end;
    Require(Failed, 'removing accepted conflicting leftover pending');
    WriteFixtureManifest(ControlPath(PendingName), 'B');
    LoadIdentity;
    Failed := False;
    try RequireRecoveryTarget('1.1.0', AHash); except Failed := True; end;
    Require(Failed, 'removing accepted installation');
    Failed := False;
    try ReadManifest(ControlPath(ManifestName), AHash, Files); except Failed := True; end;
    Require(Failed, 'bad manifest digest accepted');
    ReleaseMaintenanceLock;
    ExerciseUpgradeOwnership;
    WriteProbeReport(Output, 'PASS');
  except
    ReleaseMaintenanceLock;
    WriteProbeReport(Output, 'FAIL: ' + GetExceptionMessage);
  end;
end;
