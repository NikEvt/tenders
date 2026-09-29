#!/usr/bin/env bash
# Сборка офлайн-поставки для машины клиента под Windows.
#
# На выходе — один .zip: образы, compose, шаблон настроек и .bat-скрипты.
# Клиент распаковывает, запускает install.bat и start.bat. Ничего, кроме Docker
# Desktop, ставить не нужно, из сети скачивается только сама поставка.
#
# Что в поставку НЕ входит:
#   · embedding-service — torch и модель на 2 ГБ; фильтрам, сводке, research
#     и краулеру они не нужны, поиск по документам остаётся лексическим;
#   · какие-либо данные — тома пустые, схему накатывает migrate;
#   · какие-либо секреты — см. проверку `no_secrets` ниже. Токены клиент вводит
#     свои, пароли внутренних служб генерируются у него при первом запуске.
#
# Собирать нужно под ту архитектуру, на которой поставка поедет: Docker Desktop
# на Windows держит linux-контейнеры amd64. На Apple Silicon сборка идёт через
# эмуляцию — она работает, но стадия docs (LibreOffice, tesseract) занимает
# десятки минут. Если есть машина или раннер на amd64, собирайте там.
#
#   scripts/build_client_bundle.sh [версия] [--platform linux/arm64]

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

VERSION="${1:-$(date +%Y.%m.%d)}"
[[ "${VERSION}" == --* ]] && { echo "Первый аргумент — версия, а не флаг"; exit 2; }
shift || true

PLATFORM="linux/amd64"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform) PLATFORM="$2"; shift 2 ;;
        *) echo "Неизвестный аргумент: $1"; exit 2 ;;
    esac
done

# Адрес API так, как его видит браузер клиента. Вшивается в бандл на сборке —
# поменять его в .env на стороне клиента невозможно, только пересобрать.
WEB_API_URL="${WEB_API_URL:-http://localhost:8000}"

OUT="${ROOT}/dist"
BUNDLE="${OUT}/zakupki-${VERSION}"
ARCHIVE="${OUT}/zakupki-${VERSION}-windows.zip"

# Образы приложения: имя → (стадия, extras).
APP_IMAGES=(
    "zakupki-migrate:migrate:"
    "zakupki-crawler:app:crawler"
    "zakupki-docs:docs:"
    "zakupki-llm:app:llm"
    "zakupki-recsys:app:recsys"
    "zakupki-api:app:api"
)

# Готовые образы инфраструктуры. Их тоже кладём в архив: у клиента может не
# быть доступа к Docker Hub, а без брокера и базы стек не поднимется.
INFRA_IMAGES=(
    "pgvector/pgvector:pg16"
    "rabbitmq:3.13-management"
    "minio/minio:latest"
    "minio/mc:latest"
)

say() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
die() { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ─── Проверки до сборки ───────────────────────────────────────────────────────
command -v docker >/dev/null || die "docker не найден"
docker version >/dev/null 2>&1 || die "docker не отвечает — запустите Docker Desktop"
command -v zip >/dev/null || die "zip не найден"

# Сертификаты Минцифры лежат вне git (в .gitignore стоит *.pem), поэтому на
# чистом клоне их не будет, а сборка упадёт далеко — на COPY внутри Dockerfile.
for cert in russian_trusted_root_ca russian_trusted_sub_ca; do
    [[ -f "docker/certs/${cert}.pem" ]] || die "нет docker/certs/${cert}.pem — без него образы не соберутся"
done

# .env в контекст сборки не уезжает. Если из .dockerignore это правило когда-то
# пропадёт, локальный .env со всеми токенами уедет в слой образа.
grep -qx '\.env' .dockerignore || die ".dockerignore не исключает .env — секреты уедут в образ"
grep -qx '\.env' web/.dockerignore || die "web/.dockerignore не исключает .env"

say "Поставка ${VERSION}, платформа ${PLATFORM}"

# ─── Сборка ───────────────────────────────────────────────────────────────────
for spec in "${APP_IMAGES[@]}"; do
    IFS=: read -r name target extras <<<"${spec}"
    say "Сборка ${name}:${VERSION} (стадия ${target}${extras:+, extras ${extras}})"
    args=(build --platform "${PLATFORM}" --file docker/Dockerfile --target "${target}"
          --tag "${name}:${VERSION}")
    [[ -n "${extras}" ]] && args+=(--build-arg "EXTRAS=${extras}")
    docker "${args[@]}" .
done

say "Сборка zakupki-web:${VERSION} (API по адресу ${WEB_API_URL})"
docker build --platform "${PLATFORM}" \
    --file docker/Dockerfile.web \
    --build-arg "NEXT_PUBLIC_API_URL=${WEB_API_URL}" \
    --tag "zakupki-web:${VERSION}" \
    web

say "Загрузка образов инфраструктуры"
for image in "${INFRA_IMAGES[@]}"; do
    docker pull --platform "${PLATFORM}" "${image}"
done

# ─── Проверка на утечку секретов ──────────────────────────────────────────────
# Дешевле поймать здесь, чем объяснять потом, почему боевой токен ЕИС лежит
# у клиента в слое образа. Ищем и по именам переменных, и по фактическим
# значениям из локального .env — второе ловит даже случайный COPY файла.
say "Проверка образов на секреты"

SECRETS=()
if [[ -f .env ]]; then
    while IFS='=' read -r key value; do
        case "${key}" in
            EIS_TOKEN|LLM_API_KEY|POSTGRES_PASSWORD|RABBITMQ_PASSWORD|MINIO_ROOT_PASSWORD)
                # Пустые и заведомо ненастоящие значения ищутся по всему образу
                # и дают ложные срабатывания.
                [[ -n "${value}" && "${value}" != change-me* && ${#value} -ge 8 ]] && SECRETS+=("${value}")
                ;;
        esac
    done < <(grep -E '^[A-Z_]+=' .env || true)
fi

ALL_IMAGES=()
for spec in "${APP_IMAGES[@]}"; do ALL_IMAGES+=("${spec%%:*}:${VERSION}"); done
ALL_IMAGES+=("zakupki-web:${VERSION}")

for image in "${ALL_IMAGES[@]}"; do
    meta="$(docker image inspect "${image}" --format '{{json .Config.Env}} {{json .Config.Labels}}')"
    history="$(docker history --no-trunc --format '{{.CreatedBy}}' "${image}")"

    for secret in "${SECRETS[@]:-}"; do
        [[ -z "${secret}" ]] && continue
        if grep -qF -- "${secret}" <<<"${meta}${history}"; then
            die "${image}: в образе найдено значение из локального .env"
        fi
    done

    # Переменные с секретами не должны быть зашиты в образ вовсе: всё приходит
    # из окружения при запуске.
    if grep -Eq '"(EIS_TOKEN|LLM_API_KEY|POSTGRES_PASSWORD|RABBITMQ_PASSWORD|MINIO_ROOT_PASSWORD)=[^"]+' <<<"${meta}"; then
        die "${image}: секрет зашит в ENV образа"
    fi

    # docker create контейнер не запускает — под чужой архитектурой тоже работает.
    cid="$(docker create --platform "${PLATFORM}" "${image}" true)"
    for path in /app/.env /app/.env.local /app/.git; do
        if docker cp "${cid}:${path}" - >/dev/null 2>&1; then
            docker rm -f "${cid}" >/dev/null
            die "${image}: в образе лежит ${path}"
        fi
    done
    docker rm -f "${cid}" >/dev/null
    echo "  ✓ ${image}"
done

# ─── Сборка архива ────────────────────────────────────────────────────────────
say "Упаковка"
rm -rf "${BUNDLE}" "${ARCHIVE}"
mkdir -p "${BUNDLE}"

cp deploy/client/docker-compose.yml "${BUNDLE}/"
cp db/init.sql "${BUNDLE}/init.sql"

# .env.template — единственный файл без BOM и без CRLF. BOM попал бы в первый
# ключ и docker compose перестал бы его находить; переводы строк он понимает
# любые (проверено: \r из значений срезается).
sed "s|__TAG__|${VERSION}|" deploy/client/.env.template >"${BUNDLE}/.env.template"

# Имена файлов в поставке — латиницей. Info-ZIP на macOS не выставляет флаг
# UTF-8 в заголовке записи, и кириллическое имя приезжает в проводник Windows
# кракозябрами.

# В .bat — только ASCII, и проверка тут не для красоты. cmd.exe пересчитывает
# смещение в файле по активной кодовой странице: кириллица в батнике вместе с
# `chcp 65001` заставляет его продолжить разбор с середины слова, и установка
# у клиента падает пачкой `'м' is not recognized`. Так и случилось однажды.
for script in deploy/client/*.bat; do
    if LC_ALL=C tr -d '\11\12\15\40-\176' <"${script}" | grep -q .; then
        die "$(basename "${script}"): не-ASCII символ в .bat — cmd.exe разберёт файл неверно"
    fi
    sed 's/$/\r/' "${script}" >"${BUNDLE}/$(basename "${script}")"
done

# .ps1 и инструкция — UTF-8 **с BOM**: Windows PowerShell 5.1 без BOM читает
# скрипт как ANSI, и весь русский текст в сообщениях превращается в мусор.
# Блокнот по той же метке уверенно опознаёт кодировку инструкции.
for text in deploy/client/*.ps1 deploy/client/INSTRUKCIYA.txt; do
    dest="${BUNDLE}/$(basename "${text}")"
    printf '\xEF\xBB\xBF' >"${dest}"
    sed 's/$/\r/' "${text}" >>"${dest}"
done

say "Экспорт образов (несколько гигабайт, идёт долго)"
docker save "${ALL_IMAGES[@]}" "${INFRA_IMAGES[@]}" | gzip -1 >"${BUNDLE}/images.tar.gz"

# -0 для уже сжатого images.tar.gz: перепаковывать гигабайты ради процента
# размера — минуты работы впустую.
say "Архив"
(cd "${OUT}" && zip -r -q -0 "${ARCHIVE}" "$(basename "${BUNDLE}")")

# Контрольная сумма — чтобы клиент отличил битую передачу от битой сборки.
if command -v shasum >/dev/null; then
    (cd "${OUT}" && shasum -a 256 "$(basename "${ARCHIVE}")" >"${ARCHIVE}.sha256")
else
    (cd "${OUT}" && sha256sum "$(basename "${ARCHIVE}")" >"${ARCHIVE}.sha256")
fi

printf '\n\033[32m✓ Готово\033[0m\n'
printf '  %s (%s)\n' "${ARCHIVE}" "$(du -h "${ARCHIVE}" | cut -f1)"
printf '  %s\n\n' "${ARCHIVE}.sha256"
printf 'Клиенту: распаковать, запустить install.bat, затем start.bat.\n'
printf 'Токен ЕИС и ключ LLM он вводит свои — в поставке их нет.\n\n'
