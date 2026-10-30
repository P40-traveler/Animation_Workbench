param(
    [ValidateRange(1, 65535)]
    [int]$Port = 18765,
    [switch]$SkipBuild,
    [switch]$Rebuild,
    [switch]$SetupOnly,
    [string]$PythonExecutable
)

$ErrorActionPreference = 'Stop'
$workspaceDir = $PSScriptRoot
Set-Location -LiteralPath $workspaceDir

$venvDir = Join-Path $workspaceDir '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$requirementsPath = Join-Path $workspaceDir 'backend\requirements.txt'
$requirementsStamp = Join-Path $venvDir '.requirements.sha256'
$probeCode = "import sys, sysconfig, ssl, sqlite3, venv, ensurepip; assert sys.version_info >= (3, 11); assert sys.implementation.name == 'cpython'; assert sysconfig.get_platform().startswith('win'); assert sysconfig.get_path('scripts', scheme='venv').replace(chr(92), '/').endswith('/Scripts'); print(sys.executable)"

function Test-NativePython {
    param([string]$Executable, [string[]]$PrefixArgs = @())
    if (-not $Executable -or $Executable -match '\\WindowsApps\\') { return $null }
    try {
        # Native stderr is an error record in Windows PowerShell 5.1. Failed
        # candidates are expected; select by exit code instead of throwing.
        $probeOutput = & $Executable @PrefixArgs -I -c $probeCode 2>$null
        $probeExit = $LASTEXITCODE
        if ($probeExit -eq 0 -and $probeOutput) {
            return [string](@($probeOutput)[-1])
        }
    } catch { }
    return $null
}

function Find-NativePython {
    if ($PythonExecutable) {
        $chosen = Test-NativePython $PythonExecutable
        if ($chosen) { return $chosen }
        throw 'The supplied Python must be native Windows CPython 3.11+ with venv, SSL and SQLite.'
    }
    $candidates = @(Get-Command python.exe, python3.exe -All -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandType -eq 'Application' } | Select-Object -ExpandProperty Source -Unique)
    foreach ($candidate in $candidates) {
        $chosen = Test-NativePython $candidate
        if ($chosen) { return $chosen }
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $chosen = Test-NativePython $launcher.Source @('-3')
        if ($chosen) { return $chosen }
    }
    throw 'No compatible Windows Python 3.11+ found. Install Python, or pass -PythonExecutable with its full path. MSYS2 Python is not supported by this launcher.'
}

$createdEnvironment = $false
if (-not (Test-Path -LiteralPath $venvPython)) {
    if (Test-Path -LiteralPath $venvDir) {
        throw 'The project .venv is incomplete. Rename that directory and start again; project data is stored separately in data/.'
    }
    $basePython = Find-NativePython
    Write-Host "Creating project Python environment using: $basePython"
    & $basePython -I -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the project Python environment. No global packages were installed.' }
    $createdEnvironment = $true
}
if (-not (Test-NativePython $venvPython)) {
    throw 'The project Python environment cannot run. Its base Python may have moved. Rename .venv and start again.'
}
& $venvPython -I -c "import sys; from pathlib import Path; assert sys.prefix != sys.base_prefix; assert Path(sys.prefix).resolve() == Path(sys.argv[1]).resolve()" $venvDir
if ($LASTEXITCODE -ne 0) {
    throw 'The project interpreter is not isolated inside .venv. Dependency installation was stopped.'
}

$dependencyProbe = "import sys, fastapi, uvicorn, PIL, pydantic; assert sys.prefix != sys.base_prefix; assert int(pydantic.__version__.split('.')[0]) >= 2"
$dependenciesReady = $false
try {
    & $venvPython -I -c $dependencyProbe 2>$null
    $dependenciesReady = $LASTEXITCODE -eq 0
} catch { }
$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    $requirementsHash = [System.BitConverter]::ToString($sha256.ComputeHash([System.IO.File]::ReadAllBytes($requirementsPath))).Replace('-', '')
} finally {
    $sha256.Dispose()
}
$recordedHash = if (Test-Path -LiteralPath $requirementsStamp) { (Get-Content -LiteralPath $requirementsStamp -Raw).Trim() } else { '' }
if ($createdEnvironment -or -not $dependenciesReady -or $recordedHash -ne $requirementsHash) {
    Write-Host 'Installing Python dependencies into this project only (first run may take a few minutes)...'
    & $venvPython -I -m pip --isolated install --prefix $venvDir --disable-pip-version-check --no-input --retries 2 --timeout 20 -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Project dependency installation failed. Check the network and run start.cmd again. No global Python installation was modified.'
    }
    & $venvPython -I -c $dependencyProbe
    if ($LASTEXITCODE -ne 0) { throw 'Project Python dependency verification failed.' }
    [System.IO.File]::WriteAllText($requirementsStamp, $requirementsHash, [System.Text.Encoding]::ASCII)
}
Write-Host "Project Python: $venvPython"

$distIndex = Join-Path $workspaceDir 'frontend\dist\index.html'
$buildNeeded = -not (Test-Path -LiteralPath $distIndex)
if (-not $buildNeeded -and -not $SkipBuild) {
    $buildTime = (Get-Item -LiteralPath $distIndex).LastWriteTimeUtc
    $buildInputs = @(Get-ChildItem -LiteralPath (Join-Path $workspaceDir 'frontend\src') -File -Recurse)
    $buildInputs += @(Get-Item -LiteralPath (Join-Path $workspaceDir 'frontend\package.json'), (Join-Path $workspaceDir 'frontend\package-lock.json'), (Join-Path $workspaceDir 'frontend\index.html'), (Join-Path $workspaceDir 'frontend\vite.config.ts'), (Join-Path $workspaceDir 'frontend\tsconfig.json') -ErrorAction SilentlyContinue)
    $buildNeeded = @($buildInputs | Where-Object { $_.LastWriteTimeUtc -gt $buildTime }).Count -gt 0
}
if (($buildNeeded -or $Rebuild) -and -not $SkipBuild) {
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        throw 'The frontend needs to be built. Install Node.js, then run start.cmd again.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $workspaceDir 'frontend/node_modules'))) {
        & npm.cmd --prefix frontend ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    }
    & npm.cmd --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
}

if (-not (Test-Path -LiteralPath $distIndex)) {
    throw 'Frontend build is missing. Run start.ps1 without -SkipBuild.'
}

if ($SetupOnly) {
    Write-Host 'Project environment and frontend are ready.'
    exit 0
}
Write-Host "Open http://127.0.0.1:$Port in your browser. Press Ctrl+C to stop."
& $venvPython -I -m uvicorn app.main:app --app-dir (Join-Path $workspaceDir 'backend') --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
