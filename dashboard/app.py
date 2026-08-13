"""Streamlit-клиент поверх REST API.

Прямого доступа к БД больше нет: вся логика выборки, поиска и рекомендаций живёт
в сервисах, а дашборд — тонкий клиент. Это временный UI, пока не появится SPA.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = 120.0
PAGE_SIZE = 20

# Пресеты периодов в стиле Битрикс24 — самый частый сценарий отбора.
PERIOD_PRESETS: dict[str, int | None] = {
    "Сегодня": 0,
    "Вчера и сегодня": 1,
    "Последние 7 дней": 7,
    "Последние 30 дней": 30,
    "Всё время": None,
}

st.set_page_config(page_title="Закупки 44-ФЗ", layout="wide")


def api(method: str, path: str, **kwargs: Any) -> Any:
    """Единая точка обращения к API с внятным сообщением об ошибке."""
    try:
        response = httpx.request(
            method, f"{API_URL}{path}", timeout=REQUEST_TIMEOUT, **kwargs
        )
    except httpx.HTTPError as exc:
        st.error(f"API недоступен ({API_URL}): {exc}")
        st.stop()

    if response.status_code == 404:
        return None
    if response.status_code == 503:
        st.warning(f"Сервис временно недоступен: {response.json().get('detail', '')}")
        return None
    if response.status_code >= 400:
        st.error(f"Ошибка API {response.status_code}: {response.text[:500]}")
        return None
    return response.json()


def format_price(value: Any) -> str:
    if value in (None, ""):
        return "—"
    return f"{float(value):,.2f} ₽".replace(",", " ")


def format_dt(value: str | None, with_time: bool = True) -> str:
    if not value:
        return "—"
    date_part, _, time_part = value.partition("T")
    if not with_time:
        return date_part
    return f"{date_part} {time_part[:5]}" if time_part else date_part


def render_tender_card(tender: dict, *, show_feedback: bool = False) -> None:
    with st.container(border=True):
        header, metrics = st.columns([3, 2])

        with header:
            st.markdown(f"**{tender.get('name') or 'Без наименования'}**")
            st.caption(
                f"№ {tender['reg_num']} · {tender.get('customer_name') or 'Заказчик не указан'}"
            )
            if tender.get("okpd2_code"):
                st.caption(f"ОКПД2 {tender['okpd2_code']} — {tender.get('okpd2_name') or ''}")

            if tender.get("deadline_changed"):
                st.warning(
                    f"Срок подачи сдвинут: было {format_dt(tender.get('prev_end_date'))}, "
                    f"стало {format_dt(tender.get('end_date'))}"
                )

            documents_status = tender.get("documents_status")
            count = tender.get("document_count", 0)
            if count:
                label = {
                    "done": "документы обработаны",
                    "partial": "часть документов не обработана",
                    "processing": "документы обрабатываются",
                    "failed": "документы не обработаны",
                    "pending": "документы в очереди",
                }.get(documents_status, documents_status)
                st.caption(f"Документов: {count} ({label})")

        with metrics:
            st.metric("НМЦК", format_price(tender.get("price")))
            st.caption(f"Опубликовано: {format_dt(tender.get('publish_date'))}")
            st.caption(f"Приём заявок до: {format_dt(tender.get('end_date'))}")
            if tender.get("relevance") is not None:
                st.caption(f"Релевантность: {tender['relevance']}")

        if tender.get("explanation", {}).get("reasons"):
            st.info("Почему рекомендовано: " + "; ".join(tender["explanation"]["reasons"]))

        actions = st.columns([1, 1, 1, 3])
        with actions[0]:
            if st.button("Подробнее", key=f"detail-{tender['reg_num']}"):
                st.session_state.selected = tender["reg_num"]
                st.rerun()

        if show_feedback:
            with actions[1]:
                if st.button("👍", key=f"like-{tender['reg_num']}", help="Интересно"):
                    send_feedback(tender["tender_id"], "like")
            with actions[2]:
                if st.button("👎", key=f"dislike-{tender['reg_num']}", help="Не интересно"):
                    send_feedback(tender["tender_id"], "dislike")


def send_feedback(tender_id: int, signal: str) -> None:
    if api("POST", "/feedback", json={"tender_id": tender_id, "signal": signal}):
        st.toast("Оценка учтена — рекомендации обновятся")
        st.rerun()


def render_pagination(total_pages: int, key: str) -> None:
    if total_pages <= 1:
        return
    left, middle, right = st.columns([1, 2, 1])
    with left:
        if st.button("← Назад", disabled=st.session_state[key] <= 0, key=f"prev-{key}"):
            st.session_state[key] -= 1
            st.rerun()
    with middle:
        st.markdown(
            f"<div style='text-align:center'>Страница {st.session_state[key] + 1} "
            f"из {total_pages}</div>",
            unsafe_allow_html=True,
        )
    with right:
        if st.button(
            "Вперёд →",
            disabled=st.session_state[key] >= total_pages - 1,
            key=f"next-{key}",
        ):
            st.session_state[key] += 1
            st.rerun()


# ─── Страницы ─────────────────────────────────────────────────────────────────


def page_catalog() -> None:
    st.header("Каталог закупок")
    st.session_state.setdefault("catalog_page", 0)

    with st.sidebar:
        st.subheader("Фильтры")
        period = st.selectbox("Период публикации", list(PERIOD_PRESETS), index=2)
        query = st.text_input("Поиск по наименованию и заказчику")
        price_min = st.number_input("НМЦК от", min_value=0.0, value=0.0, step=100_000.0)
        price_max = st.number_input("НМЦК до", min_value=0.0, value=0.0, step=100_000.0)
        okpd2 = st.text_input("Префикс ОКПД2", placeholder="20.11")
        only_active = st.checkbox("Только с открытым приёмом заявок", value=True)
        deadline_changed = st.checkbox("Только с изменённым сроком")

        if st.button("Применить", use_container_width=True):
            st.session_state.catalog_page = 0
            st.rerun()

    params: dict[str, Any] = {
        "page": st.session_state.catalog_page,
        "page_size": PAGE_SIZE,
        "only_active": only_active,
        "deadline_changed": deadline_changed,
    }
    days = PERIOD_PRESETS[period]
    if days is not None:
        params["since"] = (date.today() - timedelta(days=days)).isoformat()
    if query:
        params["q"] = query
    if price_min > 0:
        params["price_min"] = price_min
    if price_max > 0:
        params["price_max"] = price_max
    if okpd2:
        params["okpd2"] = okpd2

    page = api("GET", "/tenders", params=params)
    if not page:
        return

    st.caption(f"Найдено закупок: {page['total']}")
    for tender in page["items"]:
        render_tender_card(tender, show_feedback=True)
    render_pagination(page["total_pages"], "catalog_page")


def page_search() -> None:
    st.header("Умный поиск")
    st.caption(
        "Ищет и по точным словам, и по смыслу — в том числе внутри приложенной документации."
    )
    st.session_state.setdefault("search_page", 0)

    query = st.text_input("Что ищем?", placeholder="поставка газа в баллонах")
    only_active = st.checkbox("Только активные", value=True, key="search-active")

    if not query:
        return

    page = api(
        "GET",
        "/tenders/search",
        params={
            "q": query,
            "page": st.session_state.search_page,
            "page_size": PAGE_SIZE,
            "only_active": only_active,
        },
    )
    if not page:
        return

    st.caption(f"Найдено: {page['total']}")
    for tender in page["items"]:
        render_tender_card(tender, show_feedback=True)
    render_pagination(page["total_pages"], "search_page")


def page_filters() -> None:
    st.header("ИИ-фильтры")
    st.caption(
        "Опишите нужные закупки словами. Модель разберёт запрос на условия и проверит "
        "содержание документации."
    )

    query = st.text_area(
        "Описание",
        placeholder="поставка газа в баллонах, бюджет закупки до 1млн руб",
        height=90,
    )

    preview, save = st.columns(2)
    with preview:
        if st.button("Разобрать запрос", use_container_width=True) and query:
            result = api("POST", "/filters/compile", json={"query": query})
            if result:
                st.session_state.compiled = result["spec"]

    with save:
        name = st.text_input("Название фильтра", value=query[:60] if query else "")
        if st.button("Сохранить и запустить", use_container_width=True) and query and name:
            saved = api("POST", "/filters", json={"name": name, "query": query})
            if saved:
                st.session_state.filter_id = saved["filter_id"]
                job = api(
                    "POST", f"/filters/{saved['filter_id']}/run", json={"tender_ids": []}
                )
                if job:
                    st.session_state.job_id = job["job_id"]
                    st.success(f"Фильтр сохранён (id={saved['filter_id']}), прогон запущен")

    if st.session_state.get("compiled"):
        st.subheader("Разобранные условия")
        st.json(st.session_state.compiled)

    if st.session_state.get("job_id"):
        st.subheader("Статус прогона")
        if st.button("Обновить статус"):
            st.rerun()
        job = api("GET", f"/jobs/{st.session_state.job_id}")
        if job:
            st.write(
                f"Статус: **{job['status']}** — обработано {job['processed']} из {job['total']}"
            )
            if job.get("error"):
                st.error(job["error"])
            if job.get("result"):
                st.json(job["result"])

    if st.session_state.get("filter_id"):
        st.subheader("Подошедшие закупки")
        page = api(
            "GET",
            "/tenders",
            params={"filter_id": st.session_state.filter_id, "page_size": PAGE_SIZE},
        )
        if page:
            st.caption(f"Отобрано: {page['total']}")
            for tender in page["items"]:
                render_tender_card(tender, show_feedback=True)


def page_digest() -> None:
    st.header("Сводка дня")
    target = st.date_input("Дата", value=date.today() - timedelta(days=1))

    digest = api("GET", f"/digest/{target.isoformat()}")
    if digest is None:
        st.info("Сводка за эту дату ещё не сформирована.")
        if st.button("Сформировать сейчас") and api(
            "POST", f"/digest/{target.isoformat()}", params={"force": True}
        ):
            st.success("Запрос отправлен, обновите страницу через минуту")
        return

    st.caption(
        f"Закупок за день: {digest['tender_count']} · модель: {digest.get('model') or '—'}"
    )
    st.markdown(digest["summary_md"])

    sections = digest.get("sections") or {}
    if sections.get("new_customers"):
        with st.expander("Новые заказчики"):
            for customer in sections["new_customers"]:
                st.write(f"- {customer}")


def page_recommendations() -> None:
    st.header("Рекомендации")
    st.caption("Подобраны по просмотренным, отмеченным и выигранным закупкам.")

    profile = api("GET", "/profile")
    if profile:
        if not profile["is_usable"]:
            st.info(
                f"Пока набрано сигналов: {profile['signal_count']}. "
                "Оценивайте закупки — подборка станет точнее."
            )
        else:
            stats = profile.get("price_stats") or {}
            if stats.get("median"):
                st.caption(f"Ваш обычный бюджет: около {format_price(stats['median'])}")

    limit = st.slider("Сколько показать", min_value=5, max_value=50, value=20, step=5)
    for tender in api("GET", "/recommendations", params={"limit": limit}) or []:
        render_tender_card(tender, show_feedback=True)


def page_detail(reg_num: str) -> None:
    if st.button("← К списку"):
        st.session_state.selected = None
        st.rerun()

    detail = api("GET", f"/tenders/{reg_num}")
    if detail is None:
        st.error(f"Закупка {reg_num} не найдена")
        return

    tender = detail["tender"]
    st.header(tender.get("name") or reg_num)
    st.caption(f"№ {tender['reg_num']}")

    left, right = st.columns(2)
    with left:
        st.metric("НМЦК", format_price(tender.get("price")))
        st.write(f"**Заказчик:** {tender.get('customer_name') or '—'}")
        st.write(f"**ИНН:** {tender.get('customer_inn') or '—'}")
        st.write(f"**ОКПД2:** {tender.get('okpd2_code') or '—'} {tender.get('okpd2_name') or ''}")
    with right:
        st.write(f"**Опубликовано:** {format_dt(tender.get('publish_date'))}")
        st.write(f"**Приём заявок:** {format_dt(tender.get('start_date'))} — "
                 f"{format_dt(tender.get('end_date'))}")
        st.write(f"**Статус:** {tender.get('status') or '—'}")

    if tender.get("description"):
        st.subheader("Объект закупки")
        st.write(tender["description"])

    st.subheader(f"Документация ({len(detail['documents'])})")
    for document in detail["documents"]:
        with st.container(border=True):
            columns = st.columns([4, 2, 2])
            with columns[0]:
                st.write(f"**{document['file_name'] or 'без имени'}**")
                st.caption(document.get("doc_kind_name") or "")
            with columns[1]:
                status = document["extraction_status"]
                st.caption(f"Статус: {status}")
                if document["ocr_used"]:
                    st.caption("Распознано OCR")
            with columns[2]:
                link = api("GET", f"/documents/{document['document_id']}/download")
                if link:
                    st.link_button("Скачать", link["url"], use_container_width=True)

            show_text = document["has_text"] and st.checkbox(
                "Показать текст", key=f"text-{document['document_id']}"
            )
            if show_text:
                text = api("GET", f"/documents/{document['document_id']}/text")
                if text:
                    st.text_area("Текст документа", text["content"][:20000], height=300)

    if detail["verdicts"]:
        st.subheader("Решения ИИ-фильтров")
        for verdict in detail["verdicts"]:
            with st.container(border=True):
                mark = "✅ подходит" if verdict["match"] else "❌ не подходит"
                st.write(f"Фильтр #{verdict['filter_id']}: {mark} (score {verdict['score']})")
                st.caption(verdict.get("reasoning") or "")
                for item in verdict.get("evidence") or []:
                    st.caption(f"«{item.get('quote', '')}» — стр. {item.get('page', '?')}")

    st.divider()
    actions = st.columns(3)
    with actions[0]:
        if st.button("👍 Интересно"):
            send_feedback(tender["tender_id"], "like")
    with actions[1]:
        if st.button("⭐ В шорт-лист"):
            send_feedback(tender["tender_id"], "shortlist")
    with actions[2]:
        if st.button("🏆 Выиграли") and api(
            "POST", "/wins", json={"tender_id": tender["tender_id"]}
        ):
            st.toast("Отмечено — это сильнейший сигнал для рекомендаций")


def main() -> None:
    st.session_state.setdefault("selected", None)

    if st.session_state.selected:
        page_detail(st.session_state.selected)
        return

    pages = {
        "Каталог": page_catalog,
        "Умный поиск": page_search,
        "ИИ-фильтры": page_filters,
        "Сводка дня": page_digest,
        "Рекомендации": page_recommendations,
    }
    choice = st.sidebar.radio("Раздел", list(pages))
    st.sidebar.caption(f"API: {API_URL}")
    pages[choice]()


main()
