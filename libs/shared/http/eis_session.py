"""HTTP-сессия для zakupki.gov.ru.

Живёт в общем ядре, потому что нужна двум сервисам: краулеру (SOAP-интеграция)
и docs-worker (файловое хранилище). Оба эндпоинта требуют одинаковых послаблений TLS.
"""

from __future__ import annotations

import ssl

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class EisHttpsAdapter(HTTPAdapter):
    """TLS 1.0+ и ослабленный SECLEVEL.

    Эндпоинты ЕИС не согласовывают соединение с настройками по умолчанию
    современного OpenSSL — без этого запросы не проходят вовсе.
    """

    def init_poolmanager(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


# Файловое хранилище ЕИС стоит за nginx, который отдаёт 404 на `python-requests`
# — не 403 и не 429, а именно 404, неотличимый от «файла нет». С браузерным
# User-Agent тот же URL отдаёт файл. Заголовок нужен всем клиентам ЕИС, поэтому
# живёт здесь: иначе следующий клиент будет неделю искать несуществующие файлы.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def build_session(retries: int = 3) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"],
    )
    # Адаптер обязан нести retry сам: повторный mount('https://') затёр бы его.
    session.mount("https://", EisHttpsAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = BROWSER_USER_AGENT
    return session
