# Запуск системы. При первой установке создаёт .env и останавливается: без токена
# ЕИС и ключа модели запускаться незачем — краулер и отбор всё равно не поедут.

Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot '_common.ps1')

Write-Host ''
Write-Host '=== Закупки: запуск ===' -ForegroundColor Cyan
Write-Host ''

$docker = Assert-Docker

$images = & $docker image ls -q zakupki-api
if (-not $images) {
    Write-Err 'Образы не загружены.'
    Write-Host 'Сначала запустите install.bat — он распаковывает образы в Docker.'
    Wait-Exit 1
}

if (-not (Test-Path '.env')) {
    & (Join-Path $PSScriptRoot 'setup.ps1')
    # Проверяем результат, а не код возврата: код от вызванного .ps1 в разных
    # версиях PowerShell попадает в $LASTEXITCODE по-разному, а файл либо есть,
    # либо его нет.
    if (-not (Test-Path '.env')) {
        Write-Err 'Не удалось создать файл настроек .env.'
        Wait-Exit 1
    }

    Write-Host 'Сейчас откроется .env в Блокноте. Впишите EIS_TOKEN и LLM_API_KEY,'
    Write-Host 'сохраните файл, закройте Блокнот и запустите start.bat снова.'
    Write-Host ''
    Read-Host 'Нажмите Enter, чтобы открыть файл настроек' | Out-Null
    Start-Process notepad.exe '.env'
    exit 0
}

foreach ($pair in @(
    @{ Key = 'EIS_TOKEN';   What = 'токен личного кабинета ЕИС' },
    @{ Key = 'LLM_API_KEY'; What = 'ключ доступа к языковой модели' }
)) {
    if (-not (Get-EnvValue '.env' $pair.Key)) {
        Write-Err "В файле .env не заполнен $($pair.Key) — $($pair.What)."
        Write-Host 'Сейчас откроется Блокнот: впишите значение, сохраните файл'
        Write-Host 'и запустите start.bat снова.'
        Write-Host ''
        Read-Host 'Нажмите Enter, чтобы открыть файл настроек' | Out-Null
        Start-Process notepad.exe '.env'
        exit 1
    }
}

# Шаблон приезжает с образцом folder-id. Про него легко забыть, а отказ всплывёт
# далеко — в журнале llm-service на первом же обращении к модели.
$model = Get-EnvValue '.env' 'LLM_MODEL'
if ($model -and $model.Contains('<folder-id>')) {
    Write-Warn 'В LLM_MODEL остался образец <folder-id>.'
    Write-Host 'Подставьте идентификатор своего каталога Yandex Cloud, иначе фильтры,'
    Write-Host 'сводки и отбор работать не будут. Выгрузка и разбор документов поедут.'
    Write-Host ''
}

Write-Host 'Поднимаю сервисы. Первый запуск дольше остальных: создаётся база,'
Write-Host 'накатываются миграции, разворачивается брокер — до 5 минут.'
Write-Host ''

& $docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Err 'Запустить систему не удалось.'
    Write-Host 'Что посмотреть:'
    Write-Host '  logs.bat  — журналы сервисов, там видно, что именно упало'
    Write-Host 'Если в тексте выше упоминается память — уменьшите её потребление'
    Write-Host 'по разделу «Если памяти 8 ГБ» в INSTRUKCIYA.txt.'
    Wait-Exit 1
}

Write-Host ''
Write-Host 'Жду готовности системы.' -NoNewline

$ready = $false
foreach ($attempt in 1..60) {
    Start-Sleep -Seconds 5
    Write-Host '.' -NoNewline
    try {
        $response = Invoke-WebRequest -Uri 'http://localhost:8000/health/ready' `
            -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}
Write-Host ''

if (-not $ready) {
    Write-Warn 'Система не ответила за 5 минут, но продолжает подниматься.'
    Write-Host 'Загляните в журналы: logs.bat'
    Write-Host 'На медленном диске первый запуск иногда занимает дольше.'
    Wait-Exit 1
}

Write-Host ''
Write-Host 'Готово. Интерфейс: http://localhost:3000' -ForegroundColor Green
Write-Host ''
Start-Process 'http://localhost:3000'
Start-Sleep -Seconds 3
