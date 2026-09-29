# Останавливает контейнеры. Данные остаются: база, документы и очереди лежат
# в томах Docker и переживают остановку, перезагрузку и обновление версии.

Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot '_common.ps1')

$docker = Assert-Docker

Write-Host ''
Write-Host 'Останавливаю сервисы.'
& $docker compose down

Write-Host ''
Write-Host 'Остановлено. Данные сохранены — start.bat вернёт всё как было.' -ForegroundColor Green
Wait-Exit 0
