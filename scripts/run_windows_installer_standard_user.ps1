param(
    [string]$Installer, [string]$Version, [string]$Iscc, [string]$Python,
    [string]$Workspace, [switch]$Disposable
)

$ErrorActionPreference = 'Stop'
$script:StandardUserRoot = Split-Path -Parent $PSScriptRoot

function Assert-NoReparsePath {
    param([string]$Path)
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw '验收路径不能经过重解析点'
            }
        }
        $parent = [IO.Directory]::GetParent($current)
        $current = if ($null -eq $parent) { $null } else { $parent.FullName }
    }
}

function Assert-ParentContext {
    param($Installer, $Version, $Iscc, $Python, $Workspace, $Disposable)
    # 此检查必须先于账号、目录和 ACL 操作；不提供桌面或 self-hosted 绕过开关。
    if (-not $Disposable -or -not $IsWindows -or $env:GITHUB_ACTIONS -ne 'true' -or
        $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or $env:RUNNER_OS -ne 'Windows' -or
        -not $env:RUNNER_TEMP) {
        throw '标准用户验收仅允许显式指定的一次性 Windows 托管 runner'
    }
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw '创建一次性标准账户需要 runner 管理员令牌'
    }
    if (-not [IO.Path]::IsPathFullyQualified($Workspace)) { throw '验收目录必须是绝对路径' }
    $base = [IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd('\', '/')
    $target = [IO.Path]::GetFullPath($Workspace).TrimEnd('\', '/')
    if (-not $target.StartsWith($base + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $target)) {
        throw '标准用户目录必须是 RUNNER_TEMP 内尚不存在的子目录'
    }
    Assert-NoReparsePath $target
    $job = @{ version = $Version; workspace = $target }
    if (-not $Version -or $Version -notmatch '^[0-9A-Za-z.+-]+$') { throw '版本参数无效' }
    foreach ($inputFile in @{ installer = $Installer; iscc = $Iscc; python = $Python }.GetEnumerator()) {
        if (-not $inputFile.Value) { throw '必须提供全部验收输入文件' }
        $path = [IO.Path]::GetFullPath($inputFile.Value)
        Assert-NoReparsePath $path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw '验收输入文件不存在' }
        $job[$inputFile.Key] = $path
    }
    return $job
}

function Set-ValidationWorkspaceAccess {
    param([string]$Workspace, [string]$Sid)
    # 仅调整本次新建工作目录；仓库、解释器、工具缓存与其祖先 ACL 均不修改。
    $acl = Get-Acl -LiteralPath $Workspace
    $acl.SetAccessRuleProtection($true, $false)
    $inherit = [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
    foreach ($entry in @(
        @($Sid, 'Modify'), @('S-1-5-18', 'FullControl'), @('S-1-5-32-544', 'FullControl'),
        @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'FullControl')
    )) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.SecurityIdentifier]::new($entry[0]), $entry[1], $inherit,
            [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow)
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Workspace -AclObject $acl
}

function New-ValidationProcess {
    return [Diagnostics.Process]::new()
}

function Start-ValidationProcess {
    param([hashtable]$Job, [Management.Automation.PSCredential]$Credential)
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Job.python
    $start.WorkingDirectory = $script:StandardUserRoot
    $start.UseShellExecute = $false
    $start.LoadUserProfile = $true
    $start.UserName = $Credential.UserName
    $start.Domain = [Environment]::MachineName
    $start.Password = $Credential.Password
    $start.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in @('-B', (Join-Path $script:StandardUserRoot 'scripts/windows_installer/standard_user.py'),
            '--job', (Join-Path $Job.workspace 'job.json'))) {
        [void]$start.ArgumentList.Add($argument)
    }
    # 不让 runner 的令牌、凭证或 Python 覆盖项进入标准用户子进程。
    $start.Environment.Clear()
    foreach ($name in @('SystemRoot', 'WINDIR', 'COMSPEC', 'PATHEXT', 'SystemDrive',
            'ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432', 'ProgramData')) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) { $start.Environment[$name] = $value }
    }
    $start.Environment['PATH'] = [Environment]::GetEnvironmentVariable('PATH', 'Machine')
    foreach ($name in @('GITHUB_ACTIONS', 'RUNNER_ENVIRONMENT', 'RUNNER_OS', 'RUNNER_TEMP')) {
        $start.Environment[$name] = [Environment]::GetEnvironmentVariable($name)
    }
    $start.Environment['PYTHONUTF8'] = '1'
    $start.Environment['PYTHONDONTWRITEBYTECODE'] = '1'
    $start.Environment['PYTHONIOENCODING'] = 'utf-8'
    $process = New-ValidationProcess
    $process.StartInfo = $start
    $output = $null
    $errorOutput = $null
    $started = $false
    try {
        $output = [IO.File]::Open((Join-Path $Job.workspace 'stdout.log'), [IO.FileMode]::CreateNew)
        $errorOutput = [IO.File]::Open((Join-Path $Job.workspace 'stderr.log'), [IO.FileMode]::CreateNew)
        $started = $process.Start()
        if (-not $started) { throw '无法启动标准用户 bootstrap' }
        $copyOutput = $process.StandardOutput.BaseStream.CopyToAsync($output)
        $copyError = $process.StandardError.BaseStream.CopyToAsync($errorOutput)
        # 总超时由仍持有父进程的 wrapper 处理，避免先结束父进程而遗漏安装器后代。
        if (-not $process.WaitForExit(2460000)) { throw '标准用户验收超过总时限' }
        if (-not [Threading.Tasks.Task]::WaitAll(
                [Threading.Tasks.Task[]]@($copyOutput, $copyError), 10000)) {
            throw '标准用户进程退出后输出管道仍未关闭'
        }
        # 实际任务可能是 Task[VoidTaskResult]；仍检查异常，但不让结果对象混入退出码。
        [void]$copyOutput.GetAwaiter().GetResult()
        [void]$copyError.GetAwaiter().GetResult()
        return $process.ExitCode
    } finally {
        if ($started -and -not $process.HasExited) {
            $process.Kill($true)
            if (-not $process.WaitForExit(10000)) { throw '无法停止本次标准用户进程树' }
        }
        if ($null -ne $output) { $output.Dispose() }
        if ($null -ne $errorOutput) { $errorOutput.Dispose() }
        $process.Dispose()
    }
}

function Invoke-StandardUserValidation {
    param($Installer, $Version, $Iscc, $Python, $Workspace, [switch]$Disposable)
    $account = $null
    $password = $null
    $exitCode = 1
    $stage = '环境预检'
    try {
        $job = Assert-ParentContext $Installer $Version $Iscc $Python $Workspace $Disposable
        [void](New-Item -Path $job.workspace -ItemType Directory -ErrorAction Stop)
        $stage = '创建一次性标准账户'
        $name = 'adblab_' + [Guid]::NewGuid().ToString('N').Substring(0, 12)
        $password = [Security.SecureString]::new()
        # 保证密码复杂度；随机部分不转为字符串、不写入磁盘或子进程命令行。
        foreach ($character in 'Aa1!'.ToCharArray()) { $password.AppendChar($character) }
        $alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#%^_-'
        for ($index = 0; $index -lt 36; $index++) {
            $password.AppendChar($alphabet[[Security.Cryptography.RandomNumberGenerator]::GetInt32($alphabet.Length)])
        }
        $password.MakeReadOnly()
        $account = New-LocalUser -Name $name -Password $password -Description 'ADBLab disposable CI validation' -ErrorAction Stop
        Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $account -ErrorAction Stop
        $administrators = @(Get-LocalGroupMember -SID 'S-1-5-32-544' -ErrorAction Stop)
        if ($administrators | Where-Object { [string]$_.SID -eq [string]$account.SID }) {
            throw '一次性账户意外具有管理员组成员身份'
        }
        $stage = '准备标准用户专属目录'
        Set-ValidationWorkspaceAccess $job.workspace ([string]$account.SID)
        $job.expected_sid = [string]$account.SID
        $job | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $job.workspace 'job.json') -Encoding utf8 -NoNewline
        $credential = [Management.Automation.PSCredential]::new($name, $password)
        $stage = '运行标准用户验收'
        $exitCode = Start-ValidationProcess $job $credential
        # 成功运行也保留接口可读的阶段证据；仅输出固定前缀、限定长度的摘要。
        $summaryLog = Join-Path $job.workspace 'stdout.log'
        if ($exitCode -eq 0 -and (Test-Path -LiteralPath $summaryLog -PathType Leaf)) {
            Get-Content -LiteralPath $summaryLog -Encoding utf8 |
                Where-Object { $_ -match '^(START|PASS) ' } | Select-Object -Last 100 |
                ForEach-Object { [Console]::WriteLine('| ' + $_.Substring(0, [Math]::Min($_.Length, 1024))) }
        }
    } catch {
        # 不输出完整异常对象；账号密码与环境不应进入 Actions 日志。
        [Console]::Error.WriteLine("FAIL 标准用户验收失败：$stage；仅允许一次性 runner，详见专属目录日志")
        $exitCode = 1
    } finally {
        if ($null -ne $account) {
            try {
                $current = Get-LocalUser -SID $account.SID -ErrorAction Stop
                if ([string]$current.SID -ne [string]$account.SID -or $current.Name -ne $account.Name) {
                    throw '一次性账户身份已改变'
                }
                Remove-LocalUser -SID $account.SID -ErrorAction Stop
                # 保留 profile、安装残留及所有验收日志供诊断，不删除用户证据目录。
            } catch {
                [Console]::Error.WriteLine('FAIL 无法按创建时 SID 清理一次性标准账户')
                $exitCode = 1
            }
        }
        if ($null -ne $password) { $password.Dispose() }
    }
    return [int]$exitCode
}

if ($MyInvocation.InvocationName -ne '.') {
    exit (Invoke-StandardUserValidation @PSBoundParameters)
}
