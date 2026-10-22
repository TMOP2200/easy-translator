# daemon_ctl.ps1
# Pause / resume the Easy Translator daemon around an exe build.
# (There is no external watchdog any more: the app detects games itself, in memory,
#  and nothing revives the daemon automatically -- so builds must pause it here
#  and resume it here afterwards.)
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\daemon_ctl.ps1           # stop daemon(s) (before building)
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\daemon_ctl.ps1 -Resume   # start the daemon again
param([switch]$Resume)

$ErrorActionPreference = 'Continue'
# 产物路径按脚本自身位置推导（tools\..\dist），不写死任何本机目录 —— 脚本随仓库可移植。
$exe = Join-Path $PSScriptRoot '..\dist\Easy Translator.exe'

function Stop-Daemons {
    # filter on PROCESS NAME first: a command-line pattern like '*et_desktop*' also matches
    # the shell that is running this very script -> it would kill itself.
    Get-Process -Name 'Easy Translator' -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host ('stop exe daemon pid=' + $_.Id)
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like '*et_desktop*' } | ForEach-Object {
            Write-Host ('stop source daemon pid=' + $_.ProcessId)
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}

if ($Resume) {
    if (Test-Path $exe) {
        Start-Process -FilePath $exe -ArgumentList '--daemon'
        Start-Sleep -Seconds 6
        $p = Get-Process -Name 'Easy Translator' -ErrorAction SilentlyContinue
        Write-Host ('daemon started, pids: ' + (@($p).Id -join ', '))
    } else {
        Write-Host ('exe not found: ' + $exe)
    }
} else {
    Stop-Daemons
    Start-Sleep -Seconds 2
    Write-Host 'paused (build now; then run with -Resume)'
}
