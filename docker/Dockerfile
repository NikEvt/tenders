# Один Dockerfile на все сервисы: стадии различаются набором зависимостей.
# Тяжёлые бинарники (tesseract, libreoffice) и torch не попадают в образы,
# которым они не нужны.

# ─── Общая основа ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

WORKDIR /app

# Сертификаты Минцифры: без них TLS к ЕИС не проходит (цепочка подписана ими,
# а в стандартном бандле их нет).
#
# Нужны оба. Корень — очевидно. Промежуточный (Sub CA) — потому что
# `zakupki.gov.ru` отдаёт цепочку не полностью: только лист, без звена между
# ним и корнем. Собрать цепочку клиенту не из чего, и загрузка вложений падала
# с `unable to get local issuer certificate`, притом что SOAP-эндпоинт
# `int.zakupki.gov.ru` работал — он-то полную цепочку присылает.
#
# Sub CA подчинён тому же корню, поэтому нового якоря доверия здесь не
# появляется: добавляется ровно то звено, которое сервер забывает прислать.
#
# Сертификаты лежат в репозитории, а не качаются при сборке. Прежний вариант
# тянул их с reestr-pki.ru и roskazna.gov.ru под `|| true`; оба реестра
# оказались недоступны, образ собрался «успешно» и молча не мог подключиться
# к ЕИС — отказ всплыл только в рантайме невнятной SSLCertVerificationError.
COPY docker/certs/russian_trusted_root_ca.pem \
     /usr/local/share/ca-certificates/russian_trusted_root_ca.crt
COPY docker/certs/russian_trusted_sub_ca.pem \
     /usr/local/share/ca-certificates/russian_trusted_sub_ca.crt

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates openssl \
    && update-ca-certificates \
    # Самоподписанный корень проходит verify только если он попал в бандл,
    # поэтому проверка ловит и молчаливый отказ update-ca-certificates,
    # и повреждённый файл. Сборка обязана падать здесь, а не в проде.
    && openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt \
         /usr/local/share/ca-certificates/russian_trusted_root_ca.crt \
    # Промежуточный проверяется отдельно: он обязан быть подчинён тому же
    # корню. Подменённый или чужой файл здесь и остановит сборку.
    && openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt \
         /usr/local/share/ca-certificates/russian_trusted_sub_ca.crt \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY libs ./libs
COPY services ./services
COPY alembic.ini ./
COPY migrations ./migrations

# ─── Стадия для сервисов на чистом Python ────────────────────────────────────
FROM base AS app
ARG EXTRAS=api
RUN pip install --no-cache-dir -e ".[${EXTRAS}]"

# ─── Миграции ─────────────────────────────────────────────────────────────────
FROM base AS migrate
RUN pip install --no-cache-dir -e .

# ─── docs-worker: извлечение текста и OCR ────────────────────────────────────
FROM base AS docs
# tesseract-ocr-rus — сканы ТЗ почти всегда русскоязычные;
# libreoffice — единственный надёжный путь для устаревших .doc/.xls;
# unrar-free/p7zip — вложенные архивы внутри вложений.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-rus \
        tesseract-ocr-eng \
        poppler-utils \
        libreoffice-writer \
        libreoffice-calc \
        libmagic1 \
        p7zip-full \
        unrar-free \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -e ".[docs]"

# ─── embedding-service: torch + sentence-transformers ────────────────────────
FROM base AS embedding
ENV HF_HOME=/models
# CPU-сборка torch ставится первой: с обычного PyPI подтягиваются CUDA-библиотеки
# NVIDIA на несколько гигабайт, бесполезные без GPU.
# Для GPU-развёртывания уберите этот шаг — тогда extra поставит обычный torch.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir --index-url "${TORCH_INDEX_URL}" torch
RUN pip install --no-cache-dir -e ".[embedding]"

# ─── dashboard ────────────────────────────────────────────────────────────────
FROM base AS dashboard
COPY dashboard ./dashboard
RUN pip install --no-cache-dir -e ".[dashboard]"
