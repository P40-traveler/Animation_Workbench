$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw '需要 Python 3.11 或以上版本。' }
    & $pythonCommand.Source -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 环境失败。' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络。' }
Write-Output '依赖已安装，可以启动工作台。'
