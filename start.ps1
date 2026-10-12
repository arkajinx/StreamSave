$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv }
        else { & python -m venv .venv }
        if ($LASTEXITCODE -ne 0) { throw "Install Python 3.12 or newer, then retry." }
    }
    $TaskPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    & $TaskPython -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    & $TaskPython scripts\doctor.py
    if ($LASTEXITCODE -ne 0) { throw "Finish installing the missing dependencies listed above." }
    & $TaskPython run.py
} finally { Pop-Location }
