param(
    [string]$Listen = '127.0.0.1',
    [int]$Port = 8082,
    [switch]$ShowKey
)
$ErrorActionPreference = 'Stop'
$collectorPath = Join-Path $PSScriptRoot '..\src\telemetria\collector.py'
$collectorArgs = @($collectorPath, '--listen', $Listen, '--port', "$Port")
if ($ShowKey) { $collectorArgs += '--show-key' }
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 @collectorArgs
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python @collectorArgs
} else {
    throw 'Instala Python 3.10 o posterior para Windows y vuelve a abrir PowerShell.'
}
if ($LASTEXITCODE -ne 0) { throw 'El colector terminó con un error; revisa el mensaje anterior.' }
