param([Parameter(Mandatory = $true)][string]$LiteralPath)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$shell = $null
$shortcut = $null
try {
    # 只读取已存在的 .lnk；绝不调用 Save，避免把缺失快捷方式伪造为成功。
    $file = Get-Item -LiteralPath $LiteralPath -ErrorAction Stop
    if ($file.PSIsContainer -or $file.Extension -ne '.lnk') { throw '需要已有快捷方式文件' }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($file.FullName)
    if (-not $shortcut.TargetPath -or -not $shortcut.WorkingDirectory) {
        throw '快捷方式缺少目标或工作目录'
    }
    @{ target = $shortcut.TargetPath; working_directory = $shortcut.WorkingDirectory } |
        ConvertTo-Json -Compress
} catch {
    [Console]::Error.WriteLine('FAIL 无法读取快捷方式目标和工作目录')
    exit 1
} finally {
    if ($null -ne $shortcut) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut) }
    if ($null -ne $shell) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) }
}
