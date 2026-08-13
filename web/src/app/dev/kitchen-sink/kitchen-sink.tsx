"use client";

import { FileSearch } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { Chip } from "@/shared/ui/chip";
import { DefinitionList } from "@/shared/ui/definition-list";
import { EmptyState } from "@/shared/ui/empty-state";
import { Field, Input, Textarea } from "@/shared/ui/field";
import { Bar } from "@/shared/ui/bar";
import { Banner } from "@/shared/ui/banner";
import { CopyableMono, Mono } from "@/shared/ui/mono";
import { Pill, type PillTone } from "@/shared/ui/pill";
import { Rail } from "@/shared/ui/rail/rail";
import { RowSkeleton, Skeleton } from "@/shared/ui/skeleton";
import { PageHeader, SectionHeading } from "@/shared/ui/section";
import { Table, TBody, TD, TH, THead, TR } from "@/shared/ui/table";
import { Tooltip, Kbd } from "@/shared/ui/tooltip";
import { VellumNote } from "@/shared/ui/vellum-note";
import { money, dateShort } from "@/shared/lib/format";

const now = new Date("2026-08-08T10:00:00");
const day = (offset: number) => new Date(now.getTime() + offset * 86_400_000);

const PILLS: { tone: PillTone; label: string }[] = [
  { tone: "gos", label: "Приём заявок" },
  { tone: "oak", label: "Работа комиссии" },
  { tone: "neutral", label: "Завершена" },
  { tone: "signal", label: "Отменена" },
  { tone: "moss", label: "Опубликована" },
];

export function KitchenSink() {
  return (
    <div className="flex flex-col gap-10">
      <PageHeader
        title="Витрина примитивов"
        meta="Все состояния всех примитивов. Переключите тему в шапке — контраст проверяется здесь, до того как появится хоть одна страница."
      />

      <Block title="Кнопки">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary">Основное</Button>
          <Button variant="secondary">Второстепенное</Button>
          <Button variant="ghost">Прозрачное</Button>
          <Button variant="danger">Опасное</Button>
          <Button variant="primary" loading>
            Загрузка
          </Button>
          <Button variant="primary" disabled>
            Недоступно
          </Button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button size="sm">32px</Button>
          <Button size="md">40px</Button>
          <Button size="lg">48px</Button>
        </div>
      </Block>

      <Block title="Пилюли статуса">
        <div className="flex flex-wrap gap-2">
          {PILLS.map((pill) => (
            <Pill key={pill.label} tone={pill.tone} dot>
              {pill.label}
            </Pill>
          ))}
        </div>
      </Block>

      <Block title="Шкала сроков">
        <div className="flex flex-col gap-8">
          <div className="flex items-center gap-6">
            <span className="w-24 text-caption text-text-muted">micro</span>
            <Rail published={day(-8)} start={day(-8)} deadline={day(6)} scale="micro" now={now} />
            <Rail published={day(-10)} start={day(-10)} deadline={day(1)} scale="micro" now={now} />
            <Rail published={day(-20)} start={day(-20)} deadline={day(-2)} scale="micro" now={now} />
          </div>
          <div>
            <span className="text-caption text-text-muted">meso</span>
            <Rail published={day(-8)} start={day(-7)} deadline={day(6)} scale="meso" now={now} />
          </div>
          <div>
            <span className="text-caption text-text-muted">macro со сдвинутым сроком</span>
            <Rail
              published={day(-8)}
              start={day(-7)}
              deadline={day(6)}
              previousDeadline={day(1)}
              scale="macro"
              now={now}
            />
          </div>
        </div>
      </Block>

      <Block title="Заметка на полях">
        <VellumNote
          eyebrow="ИИ-ВЕРДИКТ"
          source="qwen3.6-35b"
          extra="reasoning: low"
          actions={<Button size="sm" variant="secondary">Показать источник</Button>}
        >
          <p>В ТЗ указан гарантийный срок 36 месяцев с даты поставки.</p>
        </VellumNote>
      </Block>

      <Block title="Чипы">
        <div className="flex flex-wrap gap-2">
          <Chip kind="structural" onRemove={() => {}}>
            Санкт-Петербург
          </Chip>
          <Chip kind="semantic" onRemove={() => {}}>
            «лабораторные расходники»
          </Chip>
          <Chip kind="llm" onRemove={() => {}}>
            гарантия не менее 3 лет
          </Chip>
        </div>
      </Block>

      <Block title="Поля">
        <div className="grid max-w-2xl gap-4 md:grid-cols-2">
          <Field label="Обычное поле" htmlFor="a">
            <Input id="a" placeholder="Подсказка" />
          </Field>
          <Field label="С ошибкой" htmlFor="b" error="Введите не меньше трёх символов">
            <Input id="b" defaultValue="ла" className="border-signal-fg" />
          </Field>
          <Field label="Многострочное" htmlFor="c" className="md:col-span-2">
            <Textarea id="c" rows={3} placeholder="Опишите фильтр словами" />
          </Field>
        </div>
      </Block>

      <Block title="Таблица">
        <Table>
          <THead>
            <tr>
              <TH>Документ</TH>
              <TH>Статус</TH>
              <TH numeric>Размер</TH>
              <TH numeric>Цена</TH>
            </tr>
          </THead>
          <TBody>
            {[1, 2, 3].map((i) => (
              <TR key={i}>
                <TD>Техническое задание.pdf</TD>
                <TD>
                  <Pill tone="moss">Распознан</Pill>
                </TD>
                <TD numeric>1,2 МБ</TD>
                <TD numeric>{money(2450000 * i)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Block>

      <Block title="Определения">
        <DefinitionList
          items={[
            { label: "Заказчик", value: "ГБУЗ «Городская больница №4»" },
            { label: "ИНН", value: "7801234567", mono: true },
            { label: "Опубликовано", value: dateShort(day(-8)) },
            { label: "Способ определения", value: null },
          ]}
        />
      </Block>

      <Block title="Столбцы">
        <Card className="flex flex-col gap-1">
          <Bar label="Все за 30 дней" value={4812} max={4812} />
          <Bar label="После структурных" value={318} max={4812} />
          <Bar label="После семантики" value={96} max={4812} tone="oak" />
          <Bar label="После судьи" value={41} max={4812} tone="moss" />
        </Card>
      </Block>

      <Block title="Полосы состояния">
        <div className="flex flex-col gap-3">
          <Banner tone="oak" title="ИИ-фильтрация недоступна: модель не отвечает." body="Поиск работает по ключевым словам." />
          <Banner tone="signal" title="Выгрузка завершилась с ошибкой (код 34)." body="Организация заблокирована в личном кабинете ЕИС." />
          <Banner tone="moss" title="Фильтр сохранён." />
        </div>
      </Block>

      <Block title="Моно и копирование">
        <div className="flex flex-wrap items-center gap-6">
          <CopyableMono value="0372200012345000123" label="Реестровый номер" />
          <Mono>32.50.50</Mono>
          <Tooltip content="Командная строка" shortcut="⌘K">
            <span>
              <Kbd>⌘K</Kbd>
            </span>
          </Tooltip>
        </div>
      </Block>

      <Block title="Скелетоны и пустые состояния">
        <div className="flex flex-col gap-6">
          <div className="overflow-hidden rounded-[10px] border border-hairline">
            <RowSkeleton />
            <RowSkeleton />
          </div>
          <Skeleton className="h-24 w-full" />
          <Card padded={false}>
            <EmptyState
              icon={<FileSearch strokeWidth={1.5} />}
              title="Ничего не найдено"
              body="Уберите условие «цена до 500 000 ₽» — без него находится 1 248 закупок."
              action={<Button variant="primary">Убрать условие</Button>}
            />
          </Card>
        </div>
      </Block>
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      <SectionHeading title={title} />
      <Card>{children}</Card>
    </section>
  );
}
