param([string]$Python = '')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    if ($Python) {
        & $Python -m venv .venv
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -m venv .venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
    } else {
        throw 'Install Python 3.11 x64 from python.org, then run this script again.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed. Use -Python with a Python 3.11 executable.' }
}
& '.\.venv\Scripts\python.exe' -c "import sys; assert (3,11) <= sys.version_info[:2] < (3,13), 'Python 3.11 or 3.12 is required'"
if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python version. Use Python 3.11 x64.' }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& '.\.venv\Scripts\python.exe' -m pip install --no-deps --no-build-isolation -e .
if ($LASTEXITCODE -ne 0) { throw 'Project installation failed.' }
Write-Output 'Ready. Open Start-Golyahki.cmd. Prepare Paddle models with: .\.venv\Scripts\python.exe -m scripts.check_ocr --paddle'
