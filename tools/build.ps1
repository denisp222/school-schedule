$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$taskTemp = Join-Path $projectRoot 'build/pip-temp'
New-Item -ItemType Directory -Path $taskTemp -Force | Out-Null
$env:TEMP = $taskTemp
$env:TMP = $taskTemp
Push-Location -LiteralPath $projectRoot
try {
    & (Join-Path $projectRoot '.venv/Scripts/python.exe') -X utf8 (Join-Path $PSScriptRoot 'build_application.py')
    if ($LASTEXITCODE -ne 0) { throw 'Проверка или сборка приложения не завершена.' }
} finally { Pop-Location }
