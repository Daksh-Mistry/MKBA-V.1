param([switch]$Check, [switch]$Simulate, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProgressPreference = 'SilentlyContinue'
$roboRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $roboRoot
if (-not [Environment]::Is64BitOperatingSystem) { throw 'Robo requires 64-bit Windows.' }
$roboRuntime = Join-Path $roboRoot '.runtime'
New-Item -ItemType Directory -Path $roboRuntime -Force | Out-Null
$roboInstallLock = $null

function Get-VerifiedExecutable($Url, $Sha256, $ArchiveName, $EntryName, $Destination) {
    $archive = Join-Path $roboRuntime $ArchiveName
    if (-not (Test-Path -LiteralPath $archive) -or (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $Sha256) {
        Write-Host "Downloading $ArchiveName from its official release..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $Sha256) { throw "Checksum failed: $ArchiveName" }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    $temporary = "$Destination.installing"
    try {
        $entries = @($zip.Entries | Where-Object { $_.Name -eq $EntryName })
        if ($entries.Count -ne 1) { throw "Unexpected executable layout: $ArchiveName" }
        $entryStream = $entries[0].Open()
        $hasher = [Security.Cryptography.SHA256]::Create()
        try { $expected = [BitConverter]::ToString($hasher.ComputeHash($entryStream)).Replace('-', '') }
        finally { $entryStream.Dispose(); $hasher.Dispose() }
        if ((Test-Path -LiteralPath $Destination) -and (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash -eq $expected) { return }
        # Extract only the named executable, never paths supplied by the archive.
        # An interrupted extraction never replaces a usable executable. Existing
        # partial files from older installers are repaired against the verified ZIP.
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entries[0], $temporary, $true)
        if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash -ne $expected) { throw "Extracted checksum failed: $EntryName" }
        if (Test-Path -LiteralPath $Destination) { [IO.File]::Replace($temporary, $Destination, [NullString]::Value) }
        else { [IO.File]::Move($temporary, $Destination) }
    } finally {
        $zip.Dispose()
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

try {
    try { $roboInstallLock = [IO.File]::Open((Join-Path $roboRuntime 'install.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { throw 'Another Robo installer is running. Wait for that window to finish.' }
    $roboUv = Join-Path $roboRuntime 'uv.exe'
    Get-VerifiedExecutable 'https://github.com/astral-sh/uv/releases/download/0.12.11/uv-x86_64-pc-windows-msvc.zip' `
        'e94225dea91e051472847bd6d146d7d66c4f54ffcd1f106678866a99580845f9' 'uv-0.12.11-windows.zip' 'uv.exe' $roboUv
    $roboNode = $null
    $installedNode = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($installedNode) {
        $version = & $installedNode.Source --version
        if ($version -match '^v(\d+)\.' -and [int]$Matches[1] -ge 22) { $roboNode = $installedNode.Source }
    }
    if (-not $roboNode) {
        $roboNode = Join-Path $roboRuntime 'node.exe'
        Get-VerifiedExecutable 'https://nodejs.org/dist/v24.20.0/node-v24.20.0-win-x64.zip' `
            '6cac9ffbca8f6a47091e4b5c772e0606049c3871cb67d900c0cedde630e545ba' 'node-v24.20.0-windows.zip' 'node.exe' $roboNode
    }
    # All Python installations and caches remain inside this project.
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $roboRuntime 'python'
    $env:UV_CACHE_DIR = Join-Path $roboRuntime 'cache'
    $env:UV_PYTHON_BIN_DIR = Join-Path $roboRuntime 'python-bin'
    $env:UV_NO_MODIFY_PATH = '1'
    $env:UV_PYTHON_INSTALL_REGISTRY = '0'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONUNBUFFERED = '1'
    $roboPython = Join-Path $roboRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $roboPython)) {
        Write-Host 'Preparing a private Python 3.12 environment...'
        & $roboUv venv --managed-python --python 3.12 --seed (Join-Path $roboRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Python setup failed. Check internet access and retry.' }
    }
    $roboArgs = @((Join-Path $roboRoot 'bootstrap.py'), '--uv', $roboUv, '--node', $roboNode)
    $roboArgs += '--check'
    & $roboPython @roboArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    # Installation is finished. A second click can now reuse the running stack
    # instead of being mistaken for a concurrent installer.
    $roboInstallLock.Dispose()
    $roboInstallLock = $null
    if (-not $Check) {
        $env:ROBO_NODE_EXECUTABLE = $roboNode
        $roboRunArgs = @((Join-Path $roboRoot 'run_stack.py'))
        if ($Simulate) { $roboRunArgs += '--simulate' }
        if ($NoBrowser) { $roboRunArgs += '--no-browser' }
        & $roboPython @roboRunArgs
    }
    exit $LASTEXITCODE
} catch {
    Write-Host "Robo startup: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($roboInstallLock) { $roboInstallLock.Dispose() }
}
