// 只由测试入口编译；生产入口拒绝全部故障宏，不读取运行时启用开关。
#ifndef ADBLAB_TEST_FAULTS
  #error Test-only fault hooks require ADBLAB_TEST_FAULTS
#endif
var TestCheckpointUsed: Boolean;

function TestProcessId: LongWord;
  external 'GetCurrentProcessId@kernel32.dll stdcall';

procedure InstallerTestCheckpoint(Stage, Detail: String);
var Base: String; Action: AnsiString; Attempts: Integer; Lines: TArrayOfString;
begin
  if TestCheckpointUsed or (Stage <> '{#FaultStage}') then Exit;
  TestCheckpointUsed := True;
  Base := '{#FaultRoot}\';
  SetArrayLength(Lines, 4);
  Lines[0] := '{#FaultToken}'; Lines[1] := Stage;
  Lines[2] := IntToStr(TestProcessId); Lines[3] := Detail;
  if not SaveStringsToUTF8FileWithoutBOM(Base + 'reached.tmp', Lines, False) then
    RaiseException('Test barrier cannot publish stage');
  if not WinMoveFile(Base + 'reached.tmp', Base + 'reached', 9) then
    RaiseException('Test barrier cannot commit stage');
  // 有限等待失败必须暴露，不能把无人控制的挂起冒充故障覆盖。
  for Attempts := 1 to 1200 do begin
    if LoadStringFromFile(Base + 'action', Action) then begin
      if Action = '{#FaultToken}' + #10 + 'crash' then WinExitProcess(91);
      if Action = '{#FaultToken}' + #10 + 'continue' then Exit;
      RaiseException('Test barrier action has wrong nonce or command');
    end;
    Sleep(100);
  end;
  WinExitProcess(92);
end;

procedure InstallerTestPayloadCopied;
begin
  InstallerTestCheckpoint('payload', CurrentFilename);
end;
