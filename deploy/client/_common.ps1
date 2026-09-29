# Общее для всех скриптов поставки.
#
# Почему логика живёт в PowerShell, а .bat остались пустыми пусковыми файлами:
# cmd.exe читает батник побайтово и пересчитывает смещение в файле по текущей
# кодовой странице. Строка `chcp 65001` меняет её посреди чтения — дальше
# интерпретатор разбирает середину кириллических слов как команды и сыплет
# `'м' is not recognized as an internal or external command`. Проверено на
# машине клиента: до первой настоящей команды дело не дошло вовсе.
#
# Правило, из этого следующее: в .bat — только ASCII. Весь русский текст здесь.
# Файлы .ps1 обязаны быть в UTF-8 *с BOM*: Windows PowerShell 5.1 без BOM читает
# скрипт в ANSI, и кириллица в сообщениях превращается в мусор.

$ErrorActionPreference = 'Stop'

# [Console]::OutputEncoding здесь намеренно не трогается. Write-Host отдаёт
# строки хосту PowerShell, а тот пишет в консоль через Unicode-API — кириллица
# выводится и без этого, лишь бы сам файл был прочитан в правильной кодировке
# (за это отвечает BOM). А присваивание при проверке в контейнере проглотило
# весь вывод скрипта и вернуло код 1, ничего не сказав.

function Write-Err([string]$text) {
    Write-Host ''
    Write-Host "[ОШИБКА] $text" -ForegroundColor Red
    Write-Host ''
}

function Write-Warn([string]$text) {
    Write-Host ''
    Write-Host "[ВНИМАНИЕ] $text" -ForegroundColor Yellow
    Write-Host ''
}

function Wait-Exit([int]$code) {
    Write-Host ''
    Read-Host 'Нажмите Enter, чтобы закрыть окно' | Out-Null
    exit $code
}

# Docker Desktop прописывает docker.exe в системный PATH, но проводник узнаёт об
# изменении PATH только после перезахода в систему. Свежая установка + двойной
# щелчок по .bat — ровно тот случай, когда docker есть, а команда не находится.
function Get-DockerExe {
    $found = Get-Command docker -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }

    foreach ($base in $env:ProgramFiles, ${env:ProgramFiles(x86)}) {
        if (-not $base) { continue }
        $candidate = Join-Path $base 'Docker\Docker\resources\bin\docker.exe'
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

# Возвращает путь к docker.exe либо завершает работу с внятным объяснением.
function Assert-Docker {
    $exe = Get-DockerExe
    if (-not $exe) {
        Write-Err 'Docker не найден на этом компьютере.'
        Write-Host 'Установите Docker Desktop с сайта docker.com, запустите его'
        Write-Host 'и повторите. Если Docker уже установлен — перезайдите в систему:'
        Write-Host 'проводник узнаёт о новых программах только после нового входа.'
        Wait-Exit 1
    }

    & $exe version 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Err 'Docker установлен, но не отвечает.'
        Write-Host 'Запустите Docker Desktop и дождитесь, пока значок кита в трее'
        Write-Host 'станет зелёным, — это занимает до минуты. Затем повторите.'
        Wait-Exit 1
    }

    return $exe
}

# Читает значение ключа из .env. Возвращает $null, если ключа нет или он пуст.
function Get-EnvValue([string]$path, [string]$key) {
    if (-not (Test-Path $path)) { return $null }
    foreach ($line in Get-Content -LiteralPath $path -Encoding UTF8) {
        if ($line -match "^\s*$key\s*=\s*(.*)$") {
            $value = $Matches[1].Trim()
            if ($value) { return $value }
            return $null
        }
    }
    return $null
}
