$ErrorActionPreference = 'Stop'
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) {
    $bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path $bundled) { $python = $bundled }
}
if (-not $python) { throw 'Python 3 não encontrado. Instale o Python 3.11 ou superior.' }
& $python.Path "$PSScriptRoot\server.py"

