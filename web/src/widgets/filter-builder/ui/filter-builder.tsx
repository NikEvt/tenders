"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { Field, Input, Textarea } from "@/shared/ui/field";
import { Chip } from "@/shared/ui/chip";
import { Banner } from "@/shared/ui/banner";
import { PageHeader } from "@/shared/ui/section";
import { useToast } from "@/shared/ui/toast";
import { WaitingBlock, useWaitingSince } from "@/shared/ui/waiting-block";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { endpoints } from "@/shared/api/endpoints";
import type { ContextRule, CriteriaSpec, Term } from "@/shared/api/types";
import { useCompileFilter } from "@/features/compile-filter/model/use-compile-filter";
import { compiledConditions } from "@/features/compile-filter/ui/compiled-chips";
import { FilterFunnel } from "@/features/test-filter/ui/funnel";

const EMPTY_SPEC: CriteriaSpec = {
  name: "",
  terms: [],
  context_rules: [],
  card_pattern: null,
  okpd2_prefixes: [],
  structural: {
    regions: [],
    customer_inns: [],
    price_min: null,
    price_max: null,
    only_active: true,
  },
  version: "v1",
};

/**
 * Конструктор критерия: три панели в том порядке, в котором работает отбор.
 *
 * Где искать → что искать → как отличить своё. Порядок и есть объяснение,
 * почему модель читает единицы закупок, а не всю базу: предфильтр сужает
 * корпус, термины находят упоминания, правила по контексту решают уверенные
 * случаи бесплатно, и до судьи доходит только спорное.
 *
 * Третья панель — главная по ценности и потому не спрятана в «дополнительно»:
 * на размеченном наборе правила по контексту отсекли все ложные срабатывания,
 * не потратив ни одного токена.
 */
export function FilterBuilder() {
  const router = useRouter();
  const toast = useToast();
  const compile = useCompileFilter();

  const [name, setName] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [spec, setSpec] = React.useState<CriteriaSpec>(EMPTY_SPEC);
  const [edited, setEdited] = React.useState(false);

  const [savedId, setSavedId] = React.useState<number | null>(null);
  const compilingSince = useWaitingSince(compile.isPending);

  const save = useMutation({
    // Правленый spec уходит на сервер как есть: перекомпиляция текста откатила
    // бы снятый критерий, убранный регион и поправленный порог.
    mutationFn: () => endpoints.saveFilter(name.trim(), query.trim(), edited ? spec : undefined),
    onSuccess: (result) => {
      toast.show({ title: ru.filters.saved, tone: "moss" });
      setSavedId(result.filter_id);
    },
  });

  const patch = (next: CriteriaSpec) => {
    setSpec(next);
    setEdited(true);
  };

  const conditions = compiledConditions(spec);
  const structural = conditions.filter((c) => c.kind === "structural");

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ru.filters.builderTitle} />

      <Card className="flex flex-col gap-3">
        <Field label={ru.filters.describe} htmlFor="describe">
          <Textarea
            id="describe"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={ru.filters.describePlaceholder}
            rows={2}
          />
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            loading={compile.isPending}
            disabled={query.trim().length < 3}
            onClick={() =>
              compile.mutate(query.trim(), {
                onSuccess: (result) => {
                  setSpec(result.spec);
                  setEdited(false);
                },
              })
            }
          >
            {ru.filters.compile}
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setSpec(EMPTY_SPEC);
              setQuery("");
              setEdited(false);
            }}
          >
            {ru.common.reset}
          </Button>
          {compile.isError ? (
            <p role="alert" className="text-body-sm text-signal-fg">
              {ru.errors.llmTimeout}
            </p>
          ) : null}
        </div>

        {/* Компиляция идёт до полуминуты. Спиннера в кнопке для такого срока
            мало: тишина неотличима от зависшего интерфейса, и именно здесь
            пользователь ждёт, глядя в пустое место будущего критерия. */}
        <WaitingBlock
          title={ru.waiting.compiling}
          startedAt={compilingSince}
          hint={ru.waiting.compilingHint}
        />
      </Card>

      {edited ? (
        <Banner
          tone="moss"
          title={ru.filters.editsSaved}
          body={ru.filters.editsSavedWhy}
        />
      ) : null}

      <Panel step={1} title={ru.filters.stepWhere} hint={ru.filters.stepWhereHint}>
        <div className="flex flex-col gap-3">
          <Field label={ru.filters.cardPattern} htmlFor="card-pattern">
            <Input
              id="card-pattern"
              value={spec.card_pattern ?? ""}
              onChange={(event) =>
                patch({ ...spec, card_pattern: event.target.value || null })
              }
              placeholder="вод|сточн|лаборатор"
              className="font-mono text-mono"
            />
          </Field>

          {structural.length === 0 ? (
            <p className="text-body-sm text-text-subtle">{ru.filters.noConditions}</p>
          ) : (
            <ul className="flex flex-wrap gap-1.5">
              {structural.map((condition) => (
                <li key={condition.id}>
                  <Chip kind="structural" onRemove={() => patch(condition.remove(spec))}>
                    {condition.label}
                  </Chip>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Panel>

      <Panel step={2} title={ru.filters.stepWhat} hint={ru.filters.stepWhatHint}>
        <TermRows
          terms={spec.terms}
          onChange={(terms) => patch({ ...spec, terms })}
        />
        {spec.terms.length > 0 && !spec.terms.some((t) => t.role === "primary") ? (
          <p role="alert" className="mt-2 text-body-sm text-signal-fg">
            {ru.filters.noPrimaryTerm}
          </p>
        ) : null}
      </Panel>

      <Panel step={3} title={ru.filters.stepTell} hint={ru.filters.stepTellHint}>
        <RuleRows
          rules={spec.context_rules}
          onChange={(context_rules) => patch({ ...spec, context_rules })}
        />
      </Panel>

      <FilterFunnel filterId={savedId} />

      <Card className="flex flex-wrap items-end gap-3">
        <Field label={ru.filters.name} htmlFor="filter-name" className="min-w-64 flex-1">
          <Input
            id="filter-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={ru.filters.namePlaceholder}
          />
        </Field>
        <Button
          variant="primary"
          loading={save.isPending}
          disabled={!name.trim() || query.trim().length < 3}
          onClick={() => save.mutate()}
        >
          {ru.filters.saveFilter}
        </Button>
        {savedId !== null ? (
          <Button variant="secondary" onClick={() => router.push(`/tenders?filter_id=${savedId}`)}>
            Открыть выдачу
          </Button>
        ) : null}
      </Card>
    </div>
  );
}

function Panel({
  step,
  title,
  hint,
  vellum,
  children,
}: {
  step: number;
  title: string;
  hint: string;
  vellum?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "relative rounded-[10px] border p-6",
        vellum ? "border-vellum-edge surface-vellum pl-[27px]" : "border-hairline bg-surface",
      )}
    >
      {vellum ? (
        <span className="absolute left-0 top-0 h-full w-[3px] bg-oak-fg" aria-hidden="true" />
      ) : null}
      {/* Нумерация здесь настоящая: это порядок работы конвейера. */}
      <h2 className="flex items-baseline gap-2 text-h3">
        <span className="font-mono text-mono tnum text-text-subtle">{step}</span>
        {title}
      </h2>
      <p className="mb-3 mt-1 text-body-sm text-text-muted">{hint}</p>
      {children}
    </section>
  );
}

/**
 * Строки терминов: шаблон, название и роль.
 *
 * Роль показана переключателем, а не спрятана: вспомогательный термин сам по
 * себе ничего не значит, и закупка, где сработали только такие, отвергается
 * целиком. Пользователь, не видящий роли, не поймёт, почему находки исчезли.
 */
function TermRows({
  terms,
  onChange,
}: {
  terms: Term[];
  onChange: (terms: Term[]) => void;
}) {
  const update = (index: number, patch: Partial<Term>) =>
    onChange(terms.map((term, i) => (i === index ? { ...term, ...patch } : term)));

  return (
    <div className="flex flex-col gap-2">
      {terms.map((term, index) => (
        <div key={index} className="flex flex-wrap items-end gap-2">
          <Field label={ru.filters.termName} htmlFor={`term-name-${index}`} className="w-48">
            <Input
              id={`term-name-${index}`}
              value={term.name}
              onChange={(event) => update(index, { name: event.target.value })}
            />
          </Field>
          <Field
            label={ru.filters.termPattern}
            htmlFor={`term-pattern-${index}`}
            className="min-w-64 flex-1"
          >
            <Input
              id={`term-pattern-${index}`}
              value={term.pattern}
              onChange={(event) => update(index, { pattern: event.target.value })}
              className="font-mono text-mono"
            />
          </Field>
          <Button
            variant="ghost"
            onClick={() =>
              update(index, {
                role: term.role === "primary" ? "supporting" : "primary",
              })
            }
            title={ru.filters.roleHint}
          >
            {term.role === "primary" ? ru.filters.rolePrimary : ru.filters.roleSupporting}
          </Button>
          <Button
            variant="ghost"
            onClick={() => onChange(terms.filter((_, i) => i !== index))}
            aria-label={ru.common.delete}
          >
            ×
          </Button>
        </div>
      ))}
      <div>
        <Button
          variant="secondary"
          onClick={() => onChange([...terms, { name: "", pattern: "", role: "primary" }])}
        >
          {ru.filters.addTerm}
        </Button>
      </div>
    </div>
  );
}

/**
 * Правила по контексту.
 *
 * Окно — число со смыслом, а не ползунок «чувствительности»: ±60 символов это
 * примерно три-четыре слова, ровно столько занимает «ХПК Мариинского театра».
 * Пустое окно означает «смотреть цитату целиком», и у правил «против» это
 * почти всегда ошибка — на цитате в ±220 символов найдётся что угодно.
 */
function RuleRows({
  rules,
  onChange,
}: {
  rules: ContextRule[];
  onChange: (rules: ContextRule[]) => void;
}) {
  const update = (index: number, patch: Partial<ContextRule>) =>
    onChange(rules.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)));

  return (
    <div className="flex flex-col gap-2">
      {rules.map((rule, index) => (
        <div key={index} className="flex flex-wrap items-end gap-2">
          <Field label={ru.filters.termName} htmlFor={`rule-name-${index}`} className="w-48">
            <Input
              id={`rule-name-${index}`}
              value={rule.name}
              onChange={(event) => update(index, { name: event.target.value })}
            />
          </Field>
          <Field
            label={ru.filters.termPattern}
            htmlFor={`rule-pattern-${index}`}
            className="min-w-64 flex-1"
          >
            <Input
              id={`rule-pattern-${index}`}
              value={rule.pattern}
              onChange={(event) => update(index, { pattern: event.target.value })}
              className="font-mono text-mono"
            />
          </Field>
          <Button
            variant="ghost"
            onClick={() =>
              update(index, {
                verdict: rule.verdict === "rejected" ? "confirmed" : "rejected",
              })
            }
          >
            {rule.verdict === "rejected" ? ru.filters.ruleAgainst : ru.filters.ruleFor}
          </Button>
          <Field
            label={ru.filters.ruleWindow}
            htmlFor={`rule-window-${index}`}
            className="w-40"
          >
            <Input
              id={`rule-window-${index}`}
              type="number"
              value={rule.window ?? ""}
              placeholder={ru.filters.ruleWindowWhole}
              onChange={(event) =>
                update(index, {
                  window: event.target.value ? Number(event.target.value) : null,
                })
              }
            />
          </Field>
          <Button
            variant="ghost"
            onClick={() => onChange(rules.filter((_, i) => i !== index))}
            aria-label={ru.common.delete}
          >
            ×
          </Button>
        </div>
      ))}
      <div>
        <Button
          variant="secondary"
          onClick={() =>
            onChange([
              ...rules,
              { name: "", pattern: "", verdict: "rejected", window: 60 },
            ])
          }
        >
          {ru.filters.addRule}
        </Button>
      </div>
    </div>
  );
}
