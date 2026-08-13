import type { Metadata } from "next";
import { Card } from "@/shared/ui/card";
import { Kbd } from "@/shared/ui/tooltip";
import { PageHeader, SectionHeading } from "@/shared/ui/section";
import { VellumNote } from "@/shared/ui/vellum-note";
import { ru } from "@/shared/i18n/ru";
import { SHORTCUTS } from "@/widgets/app-shell/model/shortcuts";

export const metadata: Metadata = { title: ru.help.title };

const GLOSSARY: { term: string; meaning: string }[] = [
  {
    term: "ЕИС",
    meaning:
      "Единая информационная система в сфере закупок, zakupki.gov.ru. Источник всех извещений.",
  },
  {
    term: "ОКПД2",
    meaning:
      "Классификатор продукции по видам экономической деятельности. Код вида 32.50.50 задаёт предмет закупки; поиск идёт по префиксу.",
  },
  {
    term: "НМЦК",
    meaning: "Начальная (максимальная) цена контракта — та, от которой торгуются вниз.",
  },
  {
    term: "RRF",
    meaning:
      "Reciprocal Rank Fusion: способ смешать два списка результатов — лексический и векторный — не сравнивая их несопоставимые оценки напрямую.",
  },
  {
    term: "Эмбеддинг",
    meaning:
      "Числовой вектор текста (1024 измерения, модель deepvk/USER-bge-m3). Близкие по смыслу тексты дают близкие векторы.",
  },
  {
    term: "Чанк",
    meaning:
      "Кусок документа, на который его режут перед векторизацией. Судья читает чанки, а не файл целиком, и ссылается именно на чанк.",
  },
  {
    term: "Dead-letter",
    meaning:
      "Очередь для сообщений, которые не удалось обработать после всех повторов. Оттуда их достают руками.",
  },
];

export default function HelpPage() {
  return (
    <div className="flex flex-col gap-8">
      <PageHeader title={ru.help.title} />

      <section className="flex flex-col gap-3">
        <SectionHeading title={ru.help.shortcuts} />
        <Card padded={false} className="px-6 py-2">
          <ul>
            {SHORTCUTS.map((shortcut) => (
              <li
                key={shortcut.keys}
                className="flex items-center justify-between gap-4 border-b border-hairline py-3 last:border-0"
              >
                <span className="text-body">{shortcut.action}</span>
                <Kbd>{shortcut.keys}</Kbd>
              </li>
            ))}
          </ul>
        </Card>
      </section>

      <section className="flex flex-col gap-3">
        <SectionHeading title={ru.help.whatAiDoes} />
        <VellumNote eyebrow="ЧТО ДЕЛАЕТ МОДЕЛЬ" source="qwen3.6-35b">
          <div className="measure flex flex-col gap-3">
            <p>
              <strong>Отбор.</strong> Сначала работает дешёвая часть: SQL по карточке закупки
              и поиск по словам и по смыслу — лексический индекс и векторы объединяются
              методом RRF. На этом шаге модель не участвует, и из тысяч извещений остаются
              десятки.
            </p>
            <p>
              <strong>Судья.</strong> Дальше модель читает те фрагменты технического задания,
              которые относятся к вашему критерию, и отвечает: подходит, не подходит или
              данных нет. Третий ответ — законный: если в документах нет нужного пункта,
              модель обязана это сказать, а не догадаться.
            </p>
            <p>
              <strong>Чего модель не делает.</strong> Она не принимает решение за вас.
              Вердикт носит рекомендательный характер, и каждое утверждение ведёт к фрагменту
              документа, на котором оно основано. Если ссылки нет, рядом написано «источник
              не указан» — такое утверждение проверять нужно самому.
            </p>
          </div>
        </VellumNote>
      </section>

      <section className="flex flex-col gap-3">
        <SectionHeading title={ru.help.glossary} />
        <Card>
          <dl className="flex flex-col gap-4">
            {GLOSSARY.map((entry) => (
              <div key={entry.term}>
                <dt className="text-body font-medium text-text">{entry.term}</dt>
                <dd className="measure mt-1 text-body-sm text-text-muted">{entry.meaning}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </section>
    </div>
  );
}
