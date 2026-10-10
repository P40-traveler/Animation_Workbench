$ErrorActionPreference = 'Stop'
$pidPath = Join-Path $PSScriptRoot 'logs\service.pid'
if (Test-Path -LiteralPath $pidPath) {
    $serviceId = [int](Get-Content -LiteralPath $pidPath)
    $serviceProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$serviceId" -ErrorAction SilentlyContinue
    if ($serviceProcess -and $serviceProcess.CommandLine -like "*$PSScriptRoot*launcher.py*--serve*") {
        Stop-Process -Id $serviceId
        Remove-Item -LiteralPath $pidPath
        Write-Output '工作台服务已停止。'
    } else { Write-Output '进程已退出或标识不同，没有停止其他进程。' }
}
