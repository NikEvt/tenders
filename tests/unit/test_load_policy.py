"""Уровни нагрузки: потолки считаются от машины, а не назначаются на глаз."""

from __future__ import annotations

import pytest

from libs.shared.load_policy import (
    MAX_CRAWL_WORKERS,
    LoadLevel,
    detect_cpu_count,
    resolve,
    resolve_current,
)


class TestLevelParsing:
    """Уровень читается на старте сервиса — падать здесь нельзя."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (1, LoadLevel.BACKGROUND),
            ("2", LoadLevel.BALANCED),
            (3, LoadLevel.FULL),
        ],
    )
    def test_understands_valid_levels(self, raw: object, expected: LoadLevel) -> None:
        assert LoadLevel.parse(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "полный", 0, 4, -1, 2.5, object()])
    def test_falls_back_to_balanced_on_nonsense(self, raw: object) -> None:
        """Опечатка в настройке не должна мешать сервису подняться."""
        assert LoadLevel.parse(raw) == LoadLevel.BALANCED

    @pytest.mark.parametrize("raw", [True, False])
    def test_booleans_are_not_levels(self, raw: bool) -> None:
        """`bool` — подкласс `int`, и `True` иначе стал бы фоновым уровнем."""
        assert LoadLevel.parse(raw) == LoadLevel.BALANCED

    def test_accepts_padded_strings(self) -> None:
        assert LoadLevel.parse(" 3 ") == LoadLevel.FULL


class TestLevelsAreOrdered:
    """Уровень выше — нагрузка не ниже ни по одному параметру.

    Инвариант ради предсказуемости: «поднял уровень, а стало медленнее» —
    поведение, которого пользователь не ожидает и объяснить не сможет.
    """

    @pytest.mark.parametrize(
        "field",
        [
            "extraction_workers",
            "docs_prefetch",
            "embedding_prefetch",
            "crawl_workers",
            "llm_concurrency",
            "eis_rps",
        ],
    )
    def test_every_budget_grows_with_the_level(self, field: str) -> None:
        budgets = [
            resolve(level, cpu_count=10, memory_mb=None)
            for level in (LoadLevel.BACKGROUND, LoadLevel.BALANCED, LoadLevel.FULL)
        ]
        values = [getattr(budget, field) for budget in budgets]
        assert values == sorted(values), f"{field}: {values}"


class TestBackgroundLevel:
    def test_uses_exactly_one_extraction_process(self) -> None:
        """Фоновый уровень не занимает машину, сколько бы ядер ни было."""
        for cpus in (1, 4, 10, 64):
            budget = resolve(LoadLevel.BACKGROUND, cpu_count=cpus, memory_mb=None)
            assert budget.extraction_workers == 1
            assert budget.docs_prefetch == 2

    def test_keeps_queues_and_model_at_minimum(self) -> None:
        budget = resolve(LoadLevel.BACKGROUND, cpu_count=10, memory_mb=None)
        assert budget.embedding_prefetch == 1
        assert budget.crawl_workers == 1
        assert budget.llm_concurrency == 1


class TestCpuScaling:
    def test_full_level_takes_every_core(self) -> None:
        budget = resolve(LoadLevel.FULL, cpu_count=10, memory_mb=None)
        assert budget.extraction_workers == 10

    def test_balanced_level_takes_half(self) -> None:
        budget = resolve(LoadLevel.BALANCED, cpu_count=10, memory_mb=None)
        assert budget.extraction_workers == 5

    @pytest.mark.parametrize("level", list(LoadLevel))
    def test_single_core_machine_still_gets_a_worker(self, level: LoadLevel) -> None:
        """Округление доли вниз не имеет права обнулить пул."""
        budget = resolve(level, cpu_count=1, memory_mb=None)
        assert budget.extraction_workers == 1

    @pytest.mark.parametrize("level", list(LoadLevel))
    def test_absurd_cpu_count_is_clamped_to_one(self, level: LoadLevel) -> None:
        assert resolve(level, cpu_count=0, memory_mb=None).extraction_workers >= 1


class TestMemoryCeiling:
    """Главный ограничитель уровня 3 — память, а не ядра."""

    def test_memory_caps_the_pool_below_the_core_count(self) -> None:
        # 10 ядер, но 3 ГиБ под воркер и 900 МиБ на процесс — влезает три.
        budget = resolve(
            LoadLevel.FULL, cpu_count=10, memory_mb=3072, peak_extraction_mb=900
        )
        assert budget.extraction_workers == 3

    def test_generous_memory_does_not_raise_the_pool_above_the_cores(self) -> None:
        budget = resolve(
            LoadLevel.FULL, cpu_count=4, memory_mb=64 * 1024, peak_extraction_mb=900
        )
        assert budget.extraction_workers == 4

    def test_tight_memory_still_leaves_one_worker(self) -> None:
        """Тесный лимит — повод разбирать медленно, а не не разбирать вовсе."""
        budget = resolve(
            LoadLevel.FULL, cpu_count=10, memory_mb=256, peak_extraction_mb=900
        )
        assert budget.extraction_workers == 1

    def test_unknown_memory_falls_back_to_cores(self) -> None:
        """Вне контейнера лимит неизвестен — потолок по памяти не применяется."""
        budget = resolve(LoadLevel.FULL, cpu_count=8, memory_mb=None)
        assert budget.extraction_workers == 8

    def test_prefetch_follows_the_memory_capped_pool(self) -> None:
        """Очередь не должна тянуть больше, чем пул способен разобрать."""
        budget = resolve(
            LoadLevel.FULL, cpu_count=10, memory_mb=1800, peak_extraction_mb=900
        )
        assert budget.extraction_workers == 2
        assert budget.docs_prefetch == 4


class TestOpenMpStaysSingleThreaded:
    @pytest.mark.parametrize("level", list(LoadLevel))
    def test_never_oversubscribes_inside_a_process(self, level: LoadLevel) -> None:
        """Параллелизм берётся процессами; потоки внутри делили бы ядра дважды."""
        assert resolve(level, cpu_count=10, memory_mb=None).omp_threads == 1


class TestEisCeilings:
    def test_never_exceeds_the_measured_safe_rate(self) -> None:
        """14 запросов/с и 6 параллельных выгрузок — замер прогона ХПК/БПК."""
        for level in LoadLevel:
            budget = resolve(level, cpu_count=64, memory_mb=None)
            assert budget.eis_rps <= 14.0
            assert budget.crawl_workers <= 6


class TestDetection:
    def test_cpu_detection_returns_something_usable(self) -> None:
        assert detect_cpu_count() >= 1

    def test_resolve_current_reads_the_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("LOAD_LEVEL", "1")
        assert resolve_current().level == LoadLevel.BACKGROUND

    def test_resolve_current_defaults_to_balanced(self, monkeypatch) -> None:
        monkeypatch.delenv("LOAD_LEVEL", raising=False)
        assert resolve_current().level == LoadLevel.BALANCED

    def test_explicit_argument_wins_over_the_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("LOAD_LEVEL", "1")
        assert resolve_current(3).level == LoadLevel.FULL


class TestCrawlMemoryCeiling:
    """Выгрузка ограничена памятью так же, как разбор документов.

    Суточный архив региона распаковывается в память целиком. Замер 14 августа
    2026: три одновременных обхода — пик 633 МиБ, и краулер с лимитом 256 МиБ
    дважды перезапустился на середине страны. До этого потолка по памяти у
    выгрузки не было вовсе.
    """

    def test_a_tight_limit_collapses_to_one(self) -> None:
        budget = resolve(LoadLevel.FULL, cpu_count=8, memory_mb=256)
        assert budget.crawl_workers == 1

    def test_a_roomy_limit_keeps_the_level(self) -> None:
        budget = resolve(LoadLevel.FULL, cpu_count=8, memory_mb=4096)
        assert budget.crawl_workers == MAX_CRAWL_WORKERS

    def test_memory_never_raises_above_the_level(self) -> None:
        """Потолок памяти сужает, но не расширяет: фоновый уровень остаётся одним."""
        budget = resolve(LoadLevel.BACKGROUND, cpu_count=32, memory_mb=8192)
        assert budget.crawl_workers == 1

    def test_measured_peak_admits_three_at_the_balanced_level(self) -> None:
        budget = resolve(LoadLevel.BALANCED, cpu_count=8, memory_mb=768)
        assert budget.crawl_workers == 3

    def test_outside_a_container_the_ceiling_does_not_apply(self) -> None:
        budget = resolve(LoadLevel.FULL, cpu_count=8, memory_mb=None)
        assert budget.crawl_workers == MAX_CRAWL_WORKERS
