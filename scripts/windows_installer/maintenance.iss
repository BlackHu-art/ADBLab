// 文件归属、锁、状态提交由本模块管理；Inno 卸载日志只管理系统集成。
const
  ProtocolAppId = '{#InstallAppId}';
  MarkerName = '{#InstallMarker}';
  ManifestName = '{#InstallManifest}';
  PendingName = '{#InstallPendingManifest}';
  PreviousName = '{#InstallPreviousManifest}';
  LockName = '{#InstallLock}';
  SectionName = '{#InstallSection}';
  EntryName = '{#MainExecutable}';
  TargetVersion = '{#AppVersion}';
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#InstallAppId}_is1';
  AttrReparse = $400;
  AttrDirectory = $10;
  InvalidAttributes = $FFFFFFFF;
  GenericRead = $80000000;
  GenericWrite = $40000000;
  DeleteAccess = $10000;
  OpenExisting = 3;
  CreateNew = 1;
  FileNormal = $80;

type
  TManagedFile = record
    RelativePath: String;
    Digest: String;
  end;
  TManagedFiles = array of TManagedFile;

var
  MaintenanceHandle: LongWord;
  HasMaintenanceLock, InstallationReady: Boolean;
  RootDir, OldState, CompletedVersion, PendingVersion: String;
  CompletedDigest, PendingDigest, TargetDigest: String;
  CurrentFiles, PendingFiles, TargetFiles: TManagedFiles;

function WinCreateFile(Name: String; Access, Sharing: LongWord; Security: LongWord;
  Creation, Attributes: LongWord; Template: LongWord): LongWord;
  external 'CreateFileW@kernel32.dll stdcall';
function WinCloseHandle(Handle: LongWord): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';
function WinGetAttributes(Name: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';
function WinMoveFile(OldName, NewName: String; Flags: LongWord): Boolean;
  external 'MoveFileExW@kernel32.dll stdcall';
function WinGetFolderPath(Window: LongWord; Folder: Integer; Token, Flags: LongWord;
  Path: String): Integer;
  external 'SHGetFolderPathW@shell32.dll stdcall';
function WinGetEnvironmentVariable(Name, Buffer: String; Size: LongWord): LongWord;
  external 'GetEnvironmentVariableW@kernel32.dll stdcall';
procedure WinSetLastError(Error: LongWord);
  external 'SetLastError@kernel32.dll stdcall';
procedure WinExitProcess(ExitCode: LongWord);
  external 'ExitProcess@kernel32.dll stdcall';

procedure Require(Condition: Boolean; MessageText: String);
begin
  if not Condition then RaiseException(MessageText);
end;

function NormalPath(Path: String): String;
begin
  Result := LowerCase(RemoveBackslashUnlessRoot(ExpandFileName(Path)));
end;

function IsWithin(Path, Parent: String): Boolean;
begin
  Path := NormalPath(Path);
  Parent := NormalPath(Parent);
  Result := (Path = Parent) or (Pos(AddBackslash(Parent), AddBackslash(Path)) = 1);
end;

procedure CheckNoReparse(Path: String);
var
  Parent: String;
  Attributes: LongWord;
begin
  Path := RemoveBackslashUnlessRoot(ExpandFileName(Path));
  while Path <> '' do begin
    Attributes := WinGetAttributes(Path);
    if Attributes <> InvalidAttributes then
      Require((Attributes and AttrReparse) = 0, '安装路径包含重解析点，请选择普通目录。')
    else
      Require((DLLGetLastError = 2) or (DLLGetLastError = 3), '无法检查安装路径权限。');
    Parent := ExtractFileDir(Path);
    if NormalPath(Parent) = NormalPath(Path) then Break;
    Path := Parent;
  end;
end;

function ValidDigest(Value: String): Boolean;
var I: Integer;
begin
  Result := False;
  if Length(Value) <> 64 then Exit;
  for I := 1 to 64 do
    if Pos(Value[I], '0123456789abcdef') = 0 then Exit;
  Result := True;
end;

function ValidRelativePath(Value: String): Boolean;
var
  I, StartIndex, DotIndex: Integer;
  Part, Base: String;
begin
  Result := False;
  if Value = '' then Exit;
  for I := 1 to Length(Value) do
    if (Ord(Value[I]) < 32) or (Pos(Value[I], '\:*?"<>|') > 0) then Exit;
  StartIndex := 1;
  for I := 1 to Length(Value) + 1 do begin
    if (I > Length(Value)) or (Value[I] = '/') then begin
      Part := LowerCase(Copy(Value, StartIndex, I - StartIndex));
      if (Part = '') or (Part = '.') or (Part = '..') then Exit;
      if (Part[Length(Part)] = '.') or (Part[Length(Part)] = ' ') then Exit;
      if (Pos('.adblab-', Part) = 1) or (Pos('unins', Part) = 1) then Exit;
      DotIndex := Pos('.', Part);
      Base := Part;
      if DotIndex > 0 then Base := Copy(Part, 1, DotIndex - 1);
      if (Base = 'con') or (Base = 'prn') or (Base = 'aux') or (Base = 'nul') then Exit;
      if (Length(Base) = 4) and ((Copy(Base, 1, 3) = 'com') or (Copy(Base, 1, 3) = 'lpt')) and
        (Pos(Base[4], '0123456789¹²³') > 0) then Exit;
      StartIndex := I + 1;
    end;
  end;
  Result := True;
end;

function ManagedPath(RelativePath: String): String;
begin
  Require(ValidRelativePath(RelativePath), '安装清单包含非法路径，请保留目录后重新安装。');
  StringChangeEx(RelativePath, '/', '\', True);
  Result := AddBackslash(RootDir) + RelativePath;
  Require(IsWithin(Result, RootDir), '安装清单路径越界。');
  CheckNoReparse(Result);
  Require(not DirExists(Result), '载荷文件与现有目录冲突。');
end;

function ControlPath(Name: String): String;
begin
  Result := AddBackslash(RootDir) + Name;
  CheckNoReparse(Result);
  Require(not DirExists(Result), '安装控制文件与目录冲突。');
end;

function FindManaged(Files: TManagedFiles; RelativePath: String): Integer;
var I: Integer;
begin
  Result := -1;
  for I := 0 to GetArrayLength(Files) - 1 do
    if CompareText(Files[I].RelativePath, RelativePath) = 0 then begin
      Result := I;
      Exit;
    end;
end;

procedure ReadManifest(Path, ExpectedDigest: String; var Files: TManagedFiles);
var
  Lines: TArrayOfString;
  Bytes: AnsiString;
  I, J, Count: Integer;
  RelativePath, Digest, Other: String;
begin
  SetArrayLength(Files, 0);
  CheckNoReparse(Path);
  Require(FileExists(Path), '安装清单缺失，请保留目录后重新安装。');
  Require(ValidDigest(ExpectedDigest) and (GetSHA256OfFile(Path) = ExpectedDigest), '安装清单摘要不符。');
  Require(LoadStringFromFile(Path, Bytes), '无法读取安装清单。');
  Require((Length(Bytes) >= 3) and (Ord(Bytes[1]) = $EF) and
    (Ord(Bytes[2]) = $BB) and (Ord(Bytes[3]) = $BF), '安装清单不是 UTF-8 BOM 格式。');
  Require(LoadStringsFromFile(Path, Lines), '无法解码安装清单。');
  Count := GetArrayLength(Lines);
  Require(Count > 0, '安装清单为空。');
  SetArrayLength(Files, Count);
  for I := 0 to Count - 1 do begin
    Digest := Copy(Lines[I], 1, 64);
    RelativePath := Copy(Lines[I], 66, MaxInt);
    Require((Copy(Lines[I], 65, 1) = #9) and ValidDigest(Digest) and ValidRelativePath(RelativePath), '安装清单格式无效。');
    for J := 0 to I - 1 do begin
      Other := LowerCase(Files[J].RelativePath);
      Require((CompareText(Other, RelativePath) <> 0) and
        (Pos(Other + '/', LowerCase(RelativePath) + '/') <> 1) and
        (Pos(LowerCase(RelativePath) + '/', Other + '/') <> 1), '安装清单路径发生大小写或目录冲突。');
    end;
    Files[I].RelativePath := RelativePath;
    Files[I].Digest := Digest;
  end;
end;

function ParseVersion(Value: String; var Parts: TArrayOfString): Boolean;
var I, StartIndex, Count: Integer;
begin
  Result := False;
  SetArrayLength(Parts, 3);
  StartIndex := 1;
  Count := 0;
  if Value = '' then Exit;
  for I := 1 to Length(Value) + 1 do begin
    if (I > Length(Value)) or (Value[I] = '.') then begin
      if (Count > 2) or (I = StartIndex) then Exit;
      Parts[Count] := Copy(Value, StartIndex, I - StartIndex);
      if StrToIntDef(Parts[Count], -1) < 0 then Exit;
      Count := Count + 1;
      StartIndex := I + 1;
    end else if Pos(Value[I], '0123456789') = 0 then Exit;
  end;
  Result := Count = 3;
end;

function CompareVersions(Left, Right: String): Integer;
var A, B: TArrayOfString; I, X, Y: Integer;
begin
  Require(ParseVersion(Left, A) and ParseVersion(Right, B), '安装版本格式损坏。');
  Result := 0;
  for I := 0 to 2 do begin
    X := StrToInt(A[I]); Y := StrToInt(B[I]);
    if X < Y then begin Result := -1; Exit; end;
    if X > Y then begin Result := 1; Exit; end;
  end;
end;

procedure ReleaseMaintenanceLock;
begin
  if HasMaintenanceLock then begin
    WinCloseHandle(MaintenanceHandle);
    HasMaintenanceLock := False;
  end;
end;

procedure AcquireMaintenanceLock(FirstInstall: Boolean);
var Creation: LongWord; Path: String;
begin
  Require(not HasMaintenanceLock, '维护锁已被当前操作持有。');
  Path := ControlPath(LockName);
  Creation := OpenExisting;
  if FirstInstall then Creation := CreateNew
  else Require(FileExists(Path), '安装维护锁缺失，请保留目录后重新安装。');
  MaintenanceHandle := WinCreateFile(Path, GenericRead or GenericWrite, 0, 0, Creation, FileNormal, 0);
  Require(MaintenanceHandle <> $FFFFFFFF, '程序或工具正在使用，或目录不可写。请关闭相关程序后重试。');
  HasMaintenanceLock := True;
end;

procedure ProbeFile(Path: String);
var Handle: LongWord;
begin
  CheckNoReparse(Path);
  Require(not DirExists(Path), '待维护文件与目录冲突。');
  if not FileExists(Path) then Exit;
  Handle := WinCreateFile(Path, GenericRead or GenericWrite or DeleteAccess, 0, 0, OpenExisting, FileNormal, 0);
  Require(Handle <> $FFFFFFFF, '文件正在使用或不可写。请关闭相关程序及工具后重试。');
  WinCloseHandle(Handle);
end;

procedure ProbeParentWritable(Path: String);
var Parent, Temporary: String; Handle: LongWord;
begin
  Parent := ExtractFileDir(Path);
  while not DirExists(Parent) do begin
    Require(IsWithin(Parent, RootDir) and (NormalPath(Parent) <> NormalPath(RootDir)), '无法定位载荷父目录。');
    Parent := ExtractFileDir(Parent);
  end;
  CheckNoReparse(Parent);
  Temporary := AddBackslash(Parent) + '.adblab-write-probe.tmp';
  // 新建且随句柄关闭删除，永不覆盖已有的同名文件或删除重建文件对象。
  Handle := WinCreateFile(Temporary, GenericRead or GenericWrite or DeleteAccess, 0, 0,
    CreateNew, FileNormal or $04000000, 0);
  Require(Handle <> $FFFFFFFF, '安装目录不可写，请检查权限后重试。');
  Require(WinCloseHandle(Handle), '无法结束目录写入预检。');
end;

function RegisteredDirectory: String;
begin
  Result := '';
  if RegKeyExists(HKCU64, UninstallKey) then
    Require(RegQueryStringValue(HKCU64, UninstallKey, 'InstallLocation', Result) and (Result <> ''), '安装登记损坏，请保留目录后重新安装。');
end;

function AbsoluteHomePath(Path: String): Boolean;
var Rest, Server, Share: String; Separator: Integer;
begin
  Result := (Length(Path) >= 3) and (Copy(Path, 2, 2) = ':\') and
    (Pos(UpperCase(Copy(Path, 1, 1)), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ') > 0);
  if Result or (Copy(Path, 1, 2) <> '\\') then Exit;
  Rest := Copy(Path, 3, MaxInt);
  Separator := Pos('\', Rest);
  if Separator <= 1 then Exit;
  Server := Copy(Rest, 1, Separator - 1);
  Share := Copy(Rest, Separator + 1, MaxInt);
  Separator := Pos('\', Share);
  if Separator > 0 then Share := Copy(Share, 1, Separator - 1);
  Result := (Server <> '.') and (Server <> '?') and (Share <> '') and
    (Share <> '.') and (Share <> '..');
end;

function CurrentProfileDirectory: String;
var Buffer: String; Terminator: Integer;
begin
  // Inno 6.7.3 无 userprofile 常量；CSIDL_PROFILE 读取实际 Shell 用户目录，不创建目录。
  Buffer := StringOfChar(#0, 260);
  Require(WinGetFolderPath(0, $0028, 0, 0, Buffer) = 0, '无法确认当前用户目录，请检查 Windows 用户配置。');
  Terminator := Pos(#0, Buffer);
  Require(Terminator > 1, 'Windows 返回的用户目录为空或不完整。');
  Result := Copy(Buffer, 1, Terminator - 1);
  Require(AbsoluteHomePath(Result) and DirExists(Result), 'Windows 返回的用户目录无效。');
end;

function ProcessHomeDirectory: String;
var Buffer: String; Size, Error: LongWord;
begin
  // Python 3.11 Path.home/expanduser 使用进程环境；同时保护它与 Shell profile，避免重定向漏检。
  // 空 USERPROFILE 与缺失不同：只有 ERROR_ENVVAR_NOT_FOUND 才进入 HOMEPATH 回退。
  Buffer := StringOfChar(#0, 1);
  WinSetLastError(0);
  Size := WinGetEnvironmentVariable('USERPROFILE', Buffer, 1);
  Error := DLLGetLastError;
  if (Size = 0) and (Error = 203) then begin
    Result := GetEnv('HOMEPATH');
    if Result = '' then Exit;
    StringChangeEx(Result, '/', '\', True);
    if not AbsoluteHomePath(Result) then Result := GetEnv('HOMEDRIVE') + Result;
  end else Result := GetEnv('USERPROFILE');
  StringChangeEx(Result, '/', '\', True);
  Require(AbsoluteHomePath(Result), '进程用户目录不是完整绝对路径，请检查用户环境。');
end;

procedure CheckRootDirectory;
var Dangerous: TArrayOfString; I: Integer; ProcessHome: String;
begin
  Require((Length(RootDir) > 3) and (Copy(RootDir, 2, 2) = ':\'), '请选择本地磁盘中的独立安装目录。');
  CheckNoReparse(RootDir);
  SetArrayLength(Dangerous, 6);
  Dangerous[0] := ExpandConstant('{win}');
  Dangerous[1] := ExpandConstant('{sys}');
  Dangerous[2] := ExpandConstant('{localappdata}\ADBLab');
  Dangerous[3] := AddBackslash(CurrentProfileDirectory) + 'ADBLab';
  Dangerous[4] := ExpandConstant('{pf}');
  Dangerous[5] := ExpandConstant('{commonappdata}');
  ProcessHome := ProcessHomeDirectory;
  if ProcessHome <> '' then begin
    SetArrayLength(Dangerous, 7);
    Dangerous[6] := AddBackslash(ProcessHome) + 'ADBLab';
  end;
  for I := 0 to GetArrayLength(Dangerous) - 1 do
    Require(not IsWithin(Dangerous[I], RootDir) and not IsWithin(RootDir, Dangerous[I]), '安装目录不能覆盖系统目录、用户数据或导出目录。');
end;

function DirectoryIsEmpty(Path: String): Boolean;
var Found: TFindRec;
begin
  Result := True;
  if FindFirst(AddBackslash(Path) + '*', Found) then begin
    try
      repeat
        if (Found.Name <> '.') and (Found.Name <> '..') then begin Result := False; Break; end;
      until not FindNext(Found);
    finally
      FindClose(Found);
    end;
  end;
end;

procedure LoadIdentity;
var Marker, PresentPending, CompletedPath, Previous: String; Parts, Keys, Lines: TArrayOfString; I: Integer;
begin
  Marker := ControlPath(MarkerName);
  Require(FileExists(Marker), '安装身份缺失，请保留目录后重新安装。');
  SetArrayLength(Keys, 8);
  Keys[0] := 'FormatVersion'; Keys[1] := 'AppId'; Keys[2] := 'MainExecutable'; Keys[3] := 'State';
  Keys[4] := 'CompletedVersion'; Keys[5] := 'PendingVersion';
  Keys[6] := 'ManifestSha256'; Keys[7] := 'PendingManifestSha256';
  Require(LoadStringsFromFile(Marker, Lines), '无法读取安装身份。');
  Require((GetArrayLength(Lines) = 9) and (Lines[0] = '[' + SectionName + ']'), '安装身份含有缺失、额外或重复字段。');
  for I := 0 to 7 do
    Require(IniKeyExists(SectionName, Keys[I], Marker), '安装身份字段缺失。');
  Require((GetIniString(SectionName, 'FormatVersion', '', Marker) = '1') and
    (GetIniString(SectionName, 'AppId', '', Marker) = ProtocolAppId) and
    (GetIniString(SectionName, 'MainExecutable', '', Marker) = EntryName), '安装身份损坏，请保留目录后重新安装。');
  OldState := GetIniString(SectionName, 'State', '', Marker);
  CompletedVersion := GetIniString(SectionName, 'CompletedVersion', '', Marker);
  PendingVersion := GetIniString(SectionName, 'PendingVersion', '', Marker);
  CompletedDigest := GetIniString(SectionName, 'ManifestSha256', '', Marker);
  PendingDigest := GetIniString(SectionName, 'PendingManifestSha256', '', Marker);
  Require((OldState = 'ready') or (OldState = 'installing') or (OldState = 'removing'), '安装状态损坏。');
  SetArrayLength(CurrentFiles, 0);
  SetArrayLength(PendingFiles, 0);
  Previous := ControlPath(PreviousName);
  if CompletedVersion <> '' then begin
    Require(ParseVersion(CompletedVersion, Parts), '已完成版本格式损坏。');
    CompletedPath := ControlPath(ManifestName);
    if (OldState <> 'ready') and FileExists(CompletedPath) and
      (GetSHA256OfFile(CompletedPath) <> CompletedDigest) then begin
      Require((PendingVersion <> '') and (GetSHA256OfFile(CompletedPath) = PendingDigest), '已完成清单与待完成清单冲突。');
      CompletedPath := Previous;
    end;
    ReadManifest(CompletedPath, CompletedDigest, CurrentFiles);
    if FileExists(Previous) and (PendingVersion <> '') then
      Require(GetSHA256OfFile(Previous) = CompletedDigest, '提交日志与旧清单冲突。');
  end else begin
    Require((CompletedDigest = '') and (OldState <> 'ready') and not FileExists(Previous), '安装完成信息不完整。');
    if FileExists(ControlPath(ManifestName)) then
      Require((PendingVersion <> '') and (GetSHA256OfFile(ControlPath(ManifestName)) = PendingDigest), '首次安装提交清单冲突。');
  end;
  PresentPending := ControlPath(PendingName);
  if PendingVersion <> '' then begin
    Require((OldState <> 'ready') and ParseVersion(PendingVersion, Parts), '待完成版本信息无效。');
    ReadManifest(PresentPending, PendingDigest, PendingFiles);
  end else begin
    Require((PendingDigest = '') and (OldState <> 'installing'), '安装进行中信息不完整。');
    if FileExists(PresentPending) then begin
      // ready 提交后的同清单残留仍属于该安装；卸载中断重试必须继续识别它。
      Require(((OldState = 'ready') or (OldState = 'removing')) and
        (CompletedVersion <> '') and (GetSHA256OfFile(PresentPending) = CompletedDigest), '待完成清单与当前安装冲突。');
    end;
  end;
end;

procedure RequireRecoveryTarget(Version, Digest: String);
begin
  Require(OldState <> 'removing', '卸载尚未完成，请先继续卸载。');
  if OldState = 'installing' then
    Require((PendingVersion = Version) and (PendingDigest = Digest), '安装尚未完成，请先使用原版本且相同载荷的安装程序修复。')
  else Require(CompareVersions(Version, CompletedVersion) >= 0, '不支持降级，请保留现有安装。');
end;

procedure AtomicReplace(Source, Destination: String);
begin
  CheckNoReparse(Source);
  CheckNoReparse(Destination);
  Require(WinMoveFile(Source, Destination, 1 or 8), '无法原子提交安装信息，请重新运行原安装程序。');
end;

procedure PublishIdentity(State, Complete, Pending, CompleteHash, PendingHash: String);
var Lines: TArrayOfString; Temporary: String;
begin
  Require(HasMaintenanceLock, '没有维护锁，拒绝写入安装身份。');
  Temporary := ControlPath(MarkerName + '.tmp');
  ProbeFile(Temporary);
  SetArrayLength(Lines, 9);
  Lines[0] := '[' + SectionName + ']';
  Lines[1] := 'FormatVersion=1';
  Lines[2] := 'AppId=' + ProtocolAppId;
  Lines[3] := 'MainExecutable=' + EntryName;
  Lines[4] := 'State=' + State;
  Lines[5] := 'CompletedVersion=' + Complete;
  Lines[6] := 'PendingVersion=' + Pending;
  Lines[7] := 'ManifestSha256=' + CompleteHash;
  Lines[8] := 'PendingManifestSha256=' + PendingHash;
  Require(SaveStringsToUTF8FileWithoutBOM(Temporary, Lines, False), '无法写入安装状态。');
  AtomicReplace(Temporary, ControlPath(MarkerName));
end;

procedure PublishManifest(Source, Name: String);
var Temporary: String;
begin
  Temporary := ControlPath(Name + '.tmp');
  ProbeFile(Temporary);
  Require(CopyFile(Source, Temporary, False), '无法复制安装清单。');
  AtomicReplace(Temporary, ControlPath(Name));
end;

procedure CheckManagedFiles(Files: TManagedFiles; Deleting: Boolean);
var I, Other: Integer; Path, Actual: String; Owned: Boolean;
begin
  for I := 0 to GetArrayLength(Files) - 1 do begin
    Path := ManagedPath(Files[I].RelativePath);
    ProbeFile(Path);
    if FileExists(Path) and Deleting then begin
      Actual := GetSHA256OfFile(Path);
      Owned := Actual = Files[I].Digest;
      Other := FindManaged(PendingFiles, Files[I].RelativePath);
      if Other >= 0 then Owned := Owned or (Actual = PendingFiles[Other].Digest);
      Other := FindManaged(CurrentFiles, Files[I].RelativePath);
      if Other >= 0 then Owned := Owned or (Actual = CurrentFiles[Other].Digest);
      Require(Owned, '受管理文件已被修改，请保留文件后重试。');
    end;
  end;
end;

procedure PreflightInstall;
var I: Integer; Path: String;
begin
  ProbeFile(ControlPath(MarkerName));
  ProbeFile(ControlPath(ManifestName));
  ProbeFile(ControlPath(PendingName));
  ProbeFile(ControlPath(PreviousName));
  CheckManagedFiles(CurrentFiles, False);
  CheckManagedFiles(PendingFiles, False);
  for I := 0 to GetArrayLength(TargetFiles) - 1 do begin
    Path := ManagedPath(TargetFiles[I].RelativePath);
    ProbeFile(Path);
    ProbeParentWritable(Path);
    Require(not FileExists(Path) or (FindManaged(CurrentFiles, TargetFiles[I].RelativePath) >= 0) or
      (FindManaged(PendingFiles, TargetFiles[I].RelativePath) >= 0), '新载荷路径已有未登记文件，请保留该文件后重试。');
  end;
  for I := 0 to GetArrayLength(CurrentFiles) - 1 do
    if FindManaged(TargetFiles, CurrentFiles[I].RelativePath) < 0 then begin
      Path := ManagedPath(CurrentFiles[I].RelativePath);
      if FileExists(Path) then Require(GetSHA256OfFile(Path) = CurrentFiles[I].Digest, '待退役文件已被修改，不能自动删除。');
    end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var FirstInstall: Boolean; Registered, Embedded: String;
begin
  Result := '';
  try
    ReleaseMaintenanceLock;
    RootDir := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
    CheckRootDirectory;
    Registered := RegisteredDirectory;
    Require((Registered = '') or (NormalPath(Registered) = NormalPath(RootDir)), '请使用已登记的安装位置；损坏目录应先保留，再在原位置空目录重装。');
    FirstInstall := not DirExists(RootDir) or DirectoryIsEmpty(RootDir);
    if FirstInstall then Require(ForceDirectories(RootDir), '无法创建安装目录。');
    AcquireMaintenanceLock(FirstInstall);
    ExtractTemporaryFile(ManifestName);
    Embedded := ExpandConstant('{tmp}\') + ManifestName;
    TargetDigest := GetSHA256OfFile(Embedded);
    ReadManifest(Embedded, TargetDigest, TargetFiles);
    if not FirstInstall then begin
      LoadIdentity;
      Require((Registered <> '') or ((CompletedVersion = '') and (OldState = 'installing')), '非空目录没有有效的本产品登记，不能接管其他文件。');
      RequireRecoveryTarget(TargetVersion, TargetDigest);
    end else begin
      OldState := ''; CompletedVersion := ''; CompletedDigest := '';
      PendingVersion := ''; PendingDigest := '';
      SetArrayLength(CurrentFiles, 0); SetArrayLength(PendingFiles, 0);
    end;
    PreflightInstall;
    if OldState <> 'installing' then begin
      if FileExists(ControlPath(PreviousName)) then
        Require(DeleteFile(ControlPath(PreviousName)), '无法清理旧提交日志。');
      PublishManifest(Embedded, PendingName);
      PublishIdentity('installing', CompletedVersion, TargetVersion, CompletedDigest, TargetDigest);
    end;
    PendingVersion := TargetVersion; PendingDigest := TargetDigest;
    PendingFiles := TargetFiles;
  except
    Result := GetExceptionMessage;
    ReleaseMaintenanceLock;
  end;
end;

procedure RemoveEmptyParents(Path: String);
begin
  Path := ExtractFileDir(Path);
  while (NormalPath(Path) <> NormalPath(RootDir)) and IsWithin(Path, RootDir) do begin
    CheckNoReparse(Path);
    if not RemoveDir(Path) then Break;
    Path := ExtractFileDir(Path);
  end;
end;

procedure DeleteManaged(Path, Digest, Alternative: String);
var Actual: String;
begin
  CheckNoReparse(Path);
  if not FileExists(Path) then Exit;
  Actual := GetSHA256OfFile(Path);
  Require((Actual = Digest) or ((Alternative <> '') and (Actual = Alternative)), '受管理文件已变化，已停止删除。');
  Require(DeleteFile(Path), '文件删除失败，请关闭相关程序后重试。');
  Require(not FileExists(Path), '文件仍然存在，维护未完成。');
  RemoveEmptyParents(Path);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var I: Integer; Path, Embedded: String;
begin
  if CurStep = ssPostInstall then begin
    Require(HasMaintenanceLock, '维护锁未持有。');
    for I := 0 to GetArrayLength(TargetFiles) - 1 do begin
      Path := ManagedPath(TargetFiles[I].RelativePath);
      Require(FileExists(Path) and (GetSHA256OfFile(Path) = TargetFiles[I].Digest), '安装文件不完整，请重新运行原安装程序修复。');
    end;
    for I := 0 to GetArrayLength(CurrentFiles) - 1 do
      if FindManaged(TargetFiles, CurrentFiles[I].RelativePath) < 0 then
        DeleteManaged(ManagedPath(CurrentFiles[I].RelativePath), CurrentFiles[I].Digest, '');
    Embedded := ExpandConstant('{tmp}\') + ManifestName;
    if (CompletedVersion <> '') and not FileExists(ControlPath(PreviousName)) then
      PublishManifest(ControlPath(ManifestName), PreviousName);
    PublishManifest(Embedded, ManifestName);
    PublishIdentity('ready', TargetVersion, '', TargetDigest, '');
    Require(GetSHA256OfFile(ControlPath(PendingName)) = TargetDigest, '待完成清单冲突。');
    Require(DeleteFile(ControlPath(PendingName)), '无法清理待完成清单，请重新运行安装程序。');
    if FileExists(ControlPath(PreviousName)) then
      Require(DeleteFile(ControlPath(PreviousName)), '无法清理提交日志，请重新运行安装程序。');
    InstallationReady := True;
  end;
end;

function CanLaunch: Boolean;
begin
  Result := InstallationReady;
end;

function GetCustomSetupExitCode: Integer;
begin
  Result := 0;
  if not InstallationReady then Result := 73;
end;

procedure DeinitializeSetup;
begin
  ReleaseMaintenanceLock;
end;

function InitializeUninstall: Boolean;
var Registered: String;
begin
  Result := False;
  try
    RootDir := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
    CheckRootDirectory;
    Require(NormalPath(ExtractFileDir(ExpandConstant('{uninstallexe}'))) = NormalPath(RootDir), '卸载器已被移动，不能操作当前安装。');
    Registered := RegisteredDirectory;
    Require((Registered <> '') and (NormalPath(Registered) = NormalPath(RootDir)), '卸载器与当前安装登记不一致。');
    AcquireMaintenanceLock(False);
    LoadIdentity;
    ProbeFile(ControlPath(MarkerName));
    ProbeFile(ControlPath(ManifestName));
    ProbeFile(ControlPath(PendingName));
    ProbeFile(ControlPath(PreviousName));
    CheckManagedFiles(CurrentFiles, True);
    CheckManagedFiles(PendingFiles, True);
    Result := True;
  except
    Log(GetExceptionMessage);
    if not UninstallSilent then MsgBox(GetExceptionMessage, mbError, MB_OK);
    ReleaseMaintenanceLock;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var I, Other: Integer; Alternative, Path: String;
begin
  if CurUninstallStep = usUninstall then begin
    Require(HasMaintenanceLock, '维护锁未持有。');
    PublishIdentity('removing', CompletedVersion, PendingVersion, CompletedDigest, PendingDigest);
    for I := 0 to GetArrayLength(CurrentFiles) - 1 do begin
      Other := FindManaged(PendingFiles, CurrentFiles[I].RelativePath);
      Alternative := '';
      if Other >= 0 then Alternative := PendingFiles[Other].Digest;
      DeleteManaged(ManagedPath(CurrentFiles[I].RelativePath), CurrentFiles[I].Digest, Alternative);
    end;
    for I := 0 to GetArrayLength(PendingFiles) - 1 do
      DeleteManaged(ManagedPath(PendingFiles[I].RelativePath), PendingFiles[I].Digest, '');
  end;
  if CurUninstallStep = usPostUninstall then begin
    try
    for I := 0 to GetArrayLength(CurrentFiles) - 1 do
      Require(not FileExists(ManagedPath(CurrentFiles[I].RelativePath)), '卸载仍有载荷残留。');
    for I := 0 to GetArrayLength(PendingFiles) - 1 do
      Require(not FileExists(ManagedPath(PendingFiles[I].RelativePath)), '卸载仍有待完成载荷残留。');
    Require(not RegKeyExists(HKCU64, UninstallKey), '卸载登记仍存在，卸载未完成。');
    Require(not FileExists(ExpandConstant('{userprograms}\ADBLab\ADBLab.lnk')) and
      not FileExists(ExpandConstant('{userdesktop}\ADBLab.lnk')), '快捷方式仍存在，卸载未完成。');
    Path := ControlPath(PendingName);
    if FileExists(Path) then Require(DeleteFile(Path), '无法删除待完成清单。');
    Path := ControlPath(ManifestName);
    if FileExists(Path) then Require(DeleteFile(Path), '无法删除载荷清单。');
    Path := ControlPath(PreviousName);
    if FileExists(Path) then Require(DeleteFile(Path), '无法删除提交日志。');
    Require(DeleteFile(ControlPath(MarkerName)), '无法删除安装身份。');
    ReleaseMaintenanceLock;
    Require(DeleteFile(ControlPath(LockName)), '无法删除维护锁。');
    RemoveDir(RootDir);
    except
      // Inno 6.7.3 的该阶段会吞掉脚本异常；显式失败避免随后显示卸载成功。
      Log(GetExceptionMessage);
      if not UninstallSilent then MsgBox(GetExceptionMessage, mbError, MB_OK);
      ReleaseMaintenanceLock;
      WinExitProcess(73);
    end;
  end;
end;

procedure DeinitializeUninstall;
begin
  ReleaseMaintenanceLock;
end;
