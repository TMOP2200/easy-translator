# Easy Translator 桌面伴生 —— 一键启动
# 用法：右键「使用 PowerShell 运行」，或  powershell -ExecutionPolicy Bypass -File run.ps1
#        run.ps1 --selftest   只跑自检
#        run.ps1 --settings   只开设置窗口，不监听
# 参数原样透传给 python -m et_desktop（新增参数不用再改这个脚本）
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    # 唯一的前置条件：本机有 Python 3.11+。没装的话给一句人话，别丢一堆红色报错。
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Host "本机没找到 Python —— 这是唯一需要先装的东西。" -ForegroundColor Yellow
        Write-Host "  下载：https://www.python.org/downloads/  （装的时候勾选 Add python.exe to PATH）" -ForegroundColor Yellow
        Write-Host "  或用 winget：winget install Python.Python.3.12" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "首次运行：创建虚拟环境并安装依赖（要联网，约一两分钟）…" -ForegroundColor Cyan
    python -m venv .venv
    & $py -m pip install --quiet --upgrade pip
    & $py -m pip install --quiet -r requirements.txt
}

& $py -m et_desktop @args
