# Загружает образы из архива поставки в локальный Docker. Выполняется один раз
# при установке и повторно — при получении новой версии.

Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot '_common.ps1')

Write-Host ''
Write-Host '=== Установка «Закупки» ===' -ForegroundColor Cyan
Write-Host ''

$docker = Assert-Docker

if (-not (Test-Path 'images.tar.gz')) {
    Write-Err 'Рядом с install.bat нет файла images.tar.gz.'
    Write-Host 'Распакуйте архив поставки целиком, а не отдельными файлами,'
    Write-Host 'и запускайте install.bat из распакованной папки, а не из архиватора.'
    Wait-Exit 1
}

Write-Host 'Загрузка образов. Это занимает 5-15 минут и требует около 8 ГБ на диске.'
Write-Host ''

& $docker load -i 'images.tar.gz'
if ($LASTEXITCODE -ne 0) {
    Write-Err 'Загрузить образы не удалось.'
    Write-Host 'Чаще всего причина — нехватка места на диске C:.'
    Write-Host 'Освободить место или перенести хранилище Docker можно так:'
    Write-Host 'Docker Desktop → Settings → Resources → Advanced → Disk image location.'
    Wait-Exit 1
}

Write-Host ''
Write-Host 'Образы загружены. Дальше запустите start.bat.' -ForegroundColor Green
Wait-Exit 0
