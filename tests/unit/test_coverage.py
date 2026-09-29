"""Когда суточная выгрузка окончательна.

Правило маленькое, но на нём стоят два свойства: идемпотентность дозаказа
периода и работоспособность ручного обновления. Ошибка здесь либо перекачивает
прошлое заново, либо навсегда теряет вторую половину сегодняшнего дня.
"""

from __future__ import annotations

from datetime import date, timedelta

from services.crawler.domain.coverage import is_final

DAY = date(2026, 8, 13)


class TestFinality:
    def test_a_crawl_on_the_next_day_closes_it(self) -> None:
        assert is_final(DAY, DAY + timedelta(days=1))

    def test_a_much_later_crawl_closes_it_too(self) -> None:
        assert is_final(DAY, DAY + timedelta(days=30))

    def test_a_crawl_on_the_same_day_does_not(self) -> None:
        """Архив дописывается до полуночи: полдня — это не день."""
        assert not is_final(DAY, DAY)

    def test_a_crawl_before_the_day_does_not(self) -> None:
        """Выгрузка будущего дня бессмысленна и закрывать его не должна."""
        assert not is_final(DAY, DAY - timedelta(days=1))


class TestWhatItBuys:
    def test_today_is_never_closed(self) -> None:
        """На этом стоит кнопка обновления: перекачать сегодня можно всегда."""
        today = date.today()
        assert not is_final(today, today)

    def test_yesterday_is_closed_by_todays_pass(self) -> None:
        """А на этом — идемпотентность дневного прохода."""
        today = date.today()
        assert is_final(today - timedelta(days=1), today)


class TestOneRuleForBothQuestions:
    """Правило спрашивают из двух мест, и ответ обязан быть один.

    Краулер — про суточный архив ЕИС, сборка сводки — про то, можно ли считать
    сводку окончательной. Вопрос один: успело ли наблюдение застать конец дня.
    Пока ответов было два, второй просто отсутствовал.
    """

    def test_the_crawler_rule_delegates_to_the_shared_one(self) -> None:
        from libs.shared.day_completeness import is_closed

        for observed in (DAY - timedelta(days=1), DAY, DAY + timedelta(days=1)):
            assert is_final(DAY, observed) == is_closed(DAY, observed)
