# Журналы сервисов. Без аргументов — все сразу.
# Один сервис: logs.bat crawler
# Доступны: crawler, docs-worker, research, llm-service, recsys-service, api, web

param([Parameter(ValueFromRemainingArguments = $true)] [string[]]$Services)

Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot '_common.ps1')

$docker = Assert-Docker

Write-Host ''
Write-Host 'Журналы. Выход — Ctrl+C.' -ForegroundColor Cyan
Write-Host ''

$arguments = @('compose', 'logs', '-f', '--tail=200')
if ($Services) { $arguments += $Services }

& $docker @arguments
