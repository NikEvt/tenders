# Полная очистка: удаляет тома с базой, документами и очередями. Нужна редко —
# когда установку хотят начать с нуля. Восстановить удалённое будет нечем.

Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot '_common.ps1')

$docker = Assert-Docker

Write-Host ''
Write-Host '=== ВНИМАНИЕ: удаление всех накопленных данных ===' -ForegroundColor Red
Write-Host ''
Write-Host 'Будут стёрты: база закупок, извлечённые тексты документов, очереди,'
Write-Host 'результаты отбора и сводки. Отменить это будет нечем.'
Write-Host ''
Write-Host 'Файл .env с вашими токенами останется на месте.'
Write-Host ''

# Слово латиницей намеренно: ввод кириллицы в консоли зависит от кодовой
# страницы, и сравнение может не сойтись там, где пользователь всё сделал верно.
$answer = Read-Host 'Введите слово DELETE заглавными, чтобы продолжить'
if ($answer -cne 'DELETE') {
    Write-Host ''
    Write-Host 'Отменено, ничего не тронуто.' -ForegroundColor Green
    Wait-Exit 0
}

& $docker compose down -v

Write-Host ''
Write-Host 'Данные удалены. Следующий start.bat поднимет чистую систему.' -ForegroundColor Green
Wait-Exit 0
