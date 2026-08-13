"""Отбор подтверждённых попаданий ХПК/БПК в отдельный Excel.

Regex находит последовательность букв, а не смысл. Проверка всех совпадений
вручную по подсвеченному контексту выявила четыре класса ложных срабатываний,
три из которых системные:

    артефакт шаблона   «д. 22б ПК «Зарайский»», «блок из 2-х ПК4-101344»
                       — необязательный пробел внутри аббревиатуры склеил конец
                       одного слова с началом следующего;
    название объекта   «кровля БПК СИЗО-12», «цехах ХПК Мариинского театра»,
                       «здание "БПК"» — банно-прачечный и красильно-прачечный
                       комбинаты;
    медицина           «VO2peak — максимальное потребление кислорода»
                       — физиология, а не химия воды;
    маркировка изделия «Блок питания комбинированный БПК-5».

Список исключений задан поимённо, а не правилом: разметка сделана человеком по
каждому совпадению, и подменять её эвристикой, которая где-то ошибётся молча,
здесь незачем. Отклонённые не выбрасываются, а уходят на отдельный лист с
причиной — решение должно быть проверяемым.

    python scripts/refine_report.py --db data/market_analysis/hpk.sqlite \
        --out data/market_analysis/hpk_bpk_подтверждённые.xlsx
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from market_analysis import NOTICE_URL, REGION_NAMES, _cell

#: Ложные срабатывания: рег. номер → причина отклонения.
REJECTED: dict[str, str] = {
    # Медицинское потребление кислорода: спироэргометрия, гемодинамика, ЭКГ.
    "0373100005026000179": "медицина: индекс потребления кислорода, гемодинамика",
    "0373100005026000397": "медицина: VO2peak при нагрузочном тестировании",
    "0373100005026000329": "медицина: VO2, анаэробный порог",
    "0373100025726000071": "медицина: расчёт потребления кислорода по ЧСС",
    "0373100119526000089": "медицина: оценка максимального потребления кислорода",
    "0372100033825001094": "микробиология: потребление кислорода микобактерий при росте",
    # Артефакт шаблона: пробел внутри аббревиатуры склеил соседние слова.
    "0348200049726000077": "артефакт шаблона: «д. 22б ПК «Зарайский»» в списке адресов",
    "0348200049726000119": "артефакт шаблона: «д. 22б ПК «Зарайский»» в списке адресов",
    "0373200152826000448": "артефакт шаблона: «блок из 2-х ПК4-1013442322»",
    # БПК/ХПК как название здания или подразделения.
    "0372100001626000006": "банно-прачечный комбинат: капремонт БПК СИЗО-5",
    "0348100069026000026": "банно-прачечный комбинат: кровля БПК СИЗО-12",
    "0872400001326000040": "здание «БПК» Университета ФСИН",
    "0372100014226000001": "ХПК Мариинского театра: комбинат, не химия",
    "0372100014226000021": "ХПК Мариинского театра: комбинат, не химия",
    "0372100014226000003": "ХПК Мариинского театра: аттестация сварщиков",
    "0372100014226000013": "ХПК Мариинского театра: вывоз отходов",
    "0372100014226000036": "ХПК Мариинского театра: обслуживание автопогрузчика",
    "0372100014226000024": "ХПК Мариинского театра: электроизмерения",
    "0372100014226000040": "ХПК Мариинского театра: вентиляция и кондиционирование",
    # Совпадение с маркировкой изделия.
    "0848200000526000001": "маркировка изделия: блок питания БПК-01, БПК-5",
}

HEADERS = [
    ("Ссылка на закупку", 44),
    ("Рег. номер", 20),
    ("Наименование закупки", 58),
    ("НМЦК, руб.", 16),
    ("Заказчик", 46),
    ("ИНН", 13),
    ("Регион", 20),
    ("Опубликовано", 13),
    ("Приём заявок до", 13),
    ("ОКПД2", 20),
    ("Найдено", 26),
    ("Упоминаний", 11),
    ("Документ-источник", 38),
    ("Цитата", 95),
]

REJECTED_HEADERS = [
    ("Рег. номер", 20),
    ("Ссылка на закупку", 44),
    ("Наименование закупки", 58),
    ("НМЦК, руб.", 16),
    ("Причина отклонения", 52),
    ("Цитата", 95),
]


def build(db: sqlite3.Connection, out: Path) -> tuple[int, int]:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    wrap = Alignment(vertical="top", wrap_text=True)

    def setup(sheet, headers, colour: str):
        sheet.append([title for title, _ in headers])
        for index, (_, width) in enumerate(headers, start=1):
            cell = sheet.cell(row=1, column=index)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor=colour)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            sheet.column_dimensions[get_column_letter(index)].width = width
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"

    confirmed = workbook.active
    confirmed.title = "Подтверждённые"
    setup(confirmed, HEADERS, "1F4E78")
    rejected = workbook.create_sheet("Отклонённые")
    setup(rejected, REJECTED_HEADERS, "8B2E2E")

    rows = db.execute(
        """
        SELECT t.reg_num, t.name, t.price, t.customer_name, t.customer_inn, t.region,
               t.publish_date, t.end_date, t.okpd2_codes,
               (SELECT group_concat(DISTINCT term) FROM hits WHERE reg_num=t.reg_num),
               (SELECT count(*) FROM hits WHERE reg_num=t.reg_num)
        FROM tenders t WHERE t.reg_num IN (SELECT reg_num FROM hits)
        ORDER BY t.price DESC
        """
    ).fetchall()

    kept = dropped = 0
    for (reg, name, price, customer, inn, region, published, deadline, okpd,
         terms, mentions) in rows:
        # Цитата из документа информативнее, чем из карточки: в карточке она
        # дублирует название, которое и так есть в соседнем столбце.
        best = db.execute(
            "SELECT file_name, quote FROM hits WHERE reg_num=?"
            " ORDER BY CASE source WHEN 'document' THEN 0 ELSE 1 END, id LIMIT 1",
            (reg,),
        ).fetchone() or (None, None)

        if reg in REJECTED:
            dropped += 1
            rejected.append([
                _cell(v) for v in (
                    reg, NOTICE_URL.format(reg), name, price, REJECTED[reg], best[1],
                )
            ])
            continue

        kept += 1
        confirmed.append([
            _cell(v) for v in (
                NOTICE_URL.format(reg), reg, name, price, customer, inn,
                REGION_NAMES.get(region, region), (published or "")[:10],
                (deadline or "")[:10], okpd, terms, mentions, best[0], best[1],
            )
        ])

    for sheet in (confirmed, rejected):
        for line in sheet.iter_rows(min_row=2):
            for cell in line:
                cell.alignment = wrap
        # НМЦК — четвёртый столбец на обоих листах, хотя порядок соседних
        # колонок у них разный: на «Подтверждённых» перед ним ссылка, рег. номер
        # и название, на «Отклонённых» — рег. номер, ссылка и название.
        price_column = 4
        for line in sheet.iter_rows(min_row=2, min_col=price_column, max_col=price_column):
            line[0].number_format = "# ##0.00"

    out.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(out)
    return kept, dropped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/market_analysis/hpk.sqlite"))
    parser.add_argument("--out", type=Path,
                        default=Path("data/market_analysis/hpk_bpk_подтверждённые.xlsx"))
    args = parser.parse_args()

    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    kept, dropped = build(db, args.out)
    print(f"подтверждено {kept}, отклонено {dropped} → {args.out}")


if __name__ == "__main__":
    main()
