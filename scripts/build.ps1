param([string]$Python = '.\.venv\Scripts\python.exe')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
& $Python -m scripts.audit_release
if ($LASTEXITCODE -ne 0) { throw 'Source privacy audit failed.' }
& $Python -m PyInstaller --noconfirm --clean Golyahki.spec
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
foreach ($file in @('README.md','README.en.md','LICENSE','THIRD_PARTY_NOTICES.md','CHANGELOG.md')) {
    Copy-Item -LiteralPath $file -Destination 'dist\Golyahki' -Force
}
foreach ($folder in @('docs','examples','licenses')) {
    Copy-Item -LiteralPath $folder -Destination 'dist\Golyahki' -Recurse -Force
}
Copy-Item -LiteralPath 'golyah\schemas' -Destination 'dist\Golyahki\schemas' -Recurse -Force
New-Item -ItemType Directory -Path 'dist\Golyahki\assets' -Force | Out-Null
Copy-Item -LiteralPath 'assets\branding-subtle' -Destination 'dist\Golyahki\assets' -Recurse -Force
& $Python -m scripts.collect_licenses dist/Golyahki
if ($LASTEXITCODE -ne 0) { throw 'License collection failed.' }
& $Python -m scripts.audit_release dist/Golyahki --binary
if ($LASTEXITCODE -ne 0) { throw 'Binary privacy audit failed.' }
Write-Output 'Ready: dist\Golyahki\Golyahki.exe. Distribute the entire Golyahki folder.'
