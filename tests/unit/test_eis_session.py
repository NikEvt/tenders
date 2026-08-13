"""HTTP-сессия к ЕИС."""

from __future__ import annotations

from libs.shared.http.eis_session import BROWSER_USER_AGENT, build_session


def test_session_presents_a_browser_user_agent() -> None:
    """Файловое хранилище ЕИС отдаёт 404 на `python-requests`.

    Отказ неотличим от «файла нет», поэтому регрессия тут стоила бы недели
    поисков несуществующих файлов — она должна ловиться тестом.
    """
    session = build_session()

    assert session.headers["User-Agent"] == BROWSER_USER_AGENT
    assert "python-requests" not in session.headers["User-Agent"]


def test_retries_survive_the_https_mount() -> None:
    """Адаптер несёт retry сам: повторный mount затёр бы его."""
    adapter = build_session(retries=5).get_adapter("https://zakupki.gov.ru")
    assert adapter.max_retries.total == 5
