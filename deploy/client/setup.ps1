# Создаёт .env из .env.template при первой установке.
#
# Пароли внутренних служб (Postgres, RabbitMQ, MinIO) генерируются здесь, на
# машине пользователя, и никогда не покидают её. В поставке их нет и быть не
# может: общий на всех установок пароль — это один и тот же пароль у всех.
#
# Токен ЕИС и ключ LLM остаются пустыми: их вписывает владелец установки.

Set-Location -LiteralPath $PSScriptRoot
# Ради кодировки консоли: скрипт вызывается и из start.ps1, и сам по себе.
. (Join-Path $PSScriptRoot '_common.ps1')

if (Test-Path '.env') {
    Write-Host 'Файл .env уже есть — оставляю как есть.'
    exit 0
}

if (-not (Test-Path '.env.template')) {
    Write-Host 'Не найден .env.template. Распакуйте архив поставки целиком.' -ForegroundColor Red
    exit 1
}

function New-Password {
    # Только буквы и цифры: docker compose разбирает .env построчно и без
    # кавычек, поэтому пароль со спецсимволом однажды приедет в контейнер
    # обрезанным — и отказ всплывёт не здесь, а в подключении к базе.
    $alphabet = [char[]]((48..57) + (65..90) + (97..122))
    -join (1..28 | ForEach-Object { $alphabet | Get-Random })
}

$text = Get-Content -Raw -Encoding UTF8 '.env.template'
foreach ($key in 'POSTGRES_PASSWORD', 'RABBITMQ_PASSWORD', 'MINIO_ROOT_PASSWORD') {
    $text = [regex]::Replace($text, "(?m)^$key=.*$", "$key=$(New-Password)")
}

# Без BOM: docker compose читает .env как обычный текст и первый ключ вместе
# с меткой BOM в имени просто не находит. Set-Content для этого не годится —
# в Windows PowerShell 5.1 `-Encoding UTF8` означает «с BOM», без вариантов.
#
# Кодировка обязана лежать в переменной. Тот же вызов с `New-Object` прямо
# в аргументе разрешается в другую перегрузку WriteAllText и падает с
# NullReferenceException — воспроизведено при проверке скриптов.
$utf8NoBom = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
[IO.File]::WriteAllText((Join-Path $PSScriptRoot '.env'), $text, $utf8NoBom)

Write-Host ''
Write-Host 'Создан файл .env — пароли внутренних служб сгенерированы.' -ForegroundColor Green
Write-Host ''
Write-Host 'Осталось вписать два значения:'
Write-Host '  EIS_TOKEN    — токен из личного кабинета ЕИС'
Write-Host '  LLM_API_KEY  — ключ доступа к языковой модели'
Write-Host ''
