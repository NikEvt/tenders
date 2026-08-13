# Build brief — web interface for the 44-ФЗ procurement platform

**Read this whole file before writing code.** It is the single source of truth for scope, routes, design tokens, copy, and quality bar. Where it conflicts with your defaults, this file wins.

You are the design lead and the implementer. The client has already seen and rejected templated admin-panel work. They are paying for a point of view.

---

## 0. Context: what already exists

A working Python backend, six services behind RabbitMQ, documented in `README.md` (Russian). Summary of what the UI sits on top of:

| Service | Role | Port |
|---|---|---|
| `api` | REST/OpenAPI — catalog, search, gateway to everything else | 8000 |
| `crawler` | SOAP ЕИС → normalization → `tenders` | — |
| `docs-worker` | attachments → MinIO → text/OCR → chunks | — |
| `embedding-service` | `deepvk/USER-bge-m3`, 1024-dim vectors | 8020 |
| `llm-service` | `qwen3.6-35b-a3b` — filter compilation, document judge, digest | 8010 |
| `recsys-service` | interest profile, recommendations | 8030 |
| `dashboard` | **temporary Streamlit UI — you are replacing it** | 8501 |

Product capabilities the UI must expose:

1. **Structured + full-text filtering** — SQL conditions over the tender card, full-text over the card *and over extracted document text*.
2. **AI content filtering** — cheap candidate retrieval (lexical ⊕ vector, RRF) → an LLM judge reads the relevant ТЗ fragments and returns a verdict **with a citation to the source fragment**.
3. **Filter from free text** — «поставка газа в баллонах, бюджет до 1 млн руб» compiles into a structured filter + a semantic query + an LLM criterion.
4. **Daily digest** — map-reduce summary: per-category summaries → one overall digest (largest procurements, new customers, shifted deadlines).
5. **Recommendations** — weighted interest profile + ANN search + explainable ranking; **15% of the feed is exploration** and must be visibly labelled as such.

Constraints that the interface must honour honestly (do not hide them):

- **Single-user mode.** No auth. The profile and all ratings are global. The schema is ready for multi-user — the profile already has an id. Build the client auth-ready (see §9.10) but ship no login screen.
- **223-ФЗ is not supported.** Anywhere a law filter appears, show `44-ФЗ` as fixed and `223-ФЗ` as disabled with the tooltip «Пока не поддерживается».
- **`purchaseStatus` does not come from ЕИС** — status is computed from dates. The UI must say so where status is displayed (§8.2). This constraint is the origin of the design signature.
- **The LLM can silently degrade.** Empty `llm_criteria` + `keywords` that look like the query split into words ⇒ the model is unreachable and the backend fell back. The UI detects this and says it out loud (§9.6).
- **Ranking is linear and explainable.** Every recommendation must be able to show *why* it was ranked where it was. A trained ranker arrives later behind the same `RankerPort` — the explanation component must not assume linearity in its data shape.

---

## 1. Subject, audience, job

- **Subject:** a workbench for one procurement analyst who scans hundreds of state tender notices per day, looking for the four or five worth bidding on.
- **Audience:** that analyst. Domain-fluent, keyboard-fast, opens the app first thing in the morning and keeps it open until evening. Does not need feature tours. Does need to trust the machine's reasoning enough to act on it.
- **The interface's single job:** turn a daily flood of formal notices into a short, defensible shortlist — and make the reasoning behind every cut inspectable.

Everything below serves that sentence.

---

## 2. Design direction

### 2.1 The two references, and how they combine

**Reference A — Госуслуги.** Take the *institutional grammar*: the anchor blue `#0D4CD3`, generous rounded rectangles, high-contrast plain-language labels, wide tap targets, no ornament, no gradients-for-mood, tables that read like documents. This is what buys credibility with someone whose day is legal deadlines and reestr numbers.

**Reference B — a good big-tech office.** Not the beanbags — the *materials*. Felt acoustic panels, oak, brass, paper on a desk, warm light, plants at the edge of vision. Everything you need within reach, arranged so calmly that you want to come back. That is where the warmth comes from: in the neutrals and the materials, **not** in a bright accent colour.

**The synthesis in one line:** the official blue does the work; the warm neutrals and paper materials do the hospitality. Never the reverse — do not tint buttons warm, do not make backgrounds saturated.

### 2.2 Explicitly forbidden

These are the tells of generated design. None of them appear in this project:

- Cream `#F4F1EA`-family backgrounds with a high-contrast serif display and a terracotta/clay accent.
- Near-black canvas with one acid accent.
- Purple/violet as "the AI colour". AI content is distinguished by **material**, not by a purple badge.
- Gradient hero blocks, glassmorphism, glow shadows, `backdrop-blur` as decoration.
- Emoji in production UI. Icons are line icons, one family, one stroke width.
- A giant number + tiny label + gradient card as the dashboard opener.
- Generic `01 / 02 / 03` numbering. Numbering appears only where order is real information (the crawler retry ladder, digest sections in reading order).

### 2.3 Palette

Six named values, plus neutrals. Each has one job; do not spread them.

| Token | Hex | Job |
|---|---|---|
| `gos` | `#0D4CD3` | official actions, links, focus ring, primary buttons, active nav |
| `gos-press` | `#0A3CA8` | pressed/active state of the above |
| `ink` | `#12151A` | primary text (blue-black, not pure black) |
| `felt` | `#F2F3F0` | app canvas — a linen grey with a whisper of olive; the acoustic-panel neutral |
| `oak` | `#B5751A` | deadline urgency, warnings, «срок истекает» |
| `moss` | `#2E7355` | success, «заявка подана», «выиграно», healthy service |
| `signal` | `#D22D3D` | errors, «отменена», dead-letter, failed crawl |
| `vellum` | `#FBF7EF` | **AI-generated content surfaces only** (see §2.4) |

Neutral ramp (derive everything else from these; no ad-hoc greys):

```
--n-0:  #FFFFFF   surfaces, cards, table rows
--n-25: #FAFAF8   subtle row banding, input backgrounds
--n-50: #F2F3F0   canvas (= felt)
--n-100:#E7E9E4   hairlines, dividers, table borders
--n-200:#D2D6CE   disabled borders, chart gridlines
--n-400:#8D948B   secondary text, placeholders (AA on n-0)
--n-600:#5A615A   tertiary labels, captions
--n-900:#12151A   primary text (= ink)
```

Tints for status pills — 8% of the hue over `n-0`, never the full-saturation colour as a background:

```
--gos-tint:    #E8EEFC
--oak-tint:    #F7EEDD
--moss-tint:   #E5F0EA
--signal-tint: #FBE9EA
```

**Dark theme** is required. It is not an inversion: canvas becomes `#14161A`, surfaces `#1B1E23`, hairlines `#282C32`, `gos` lightens to `#5B8DEF` for contrast, `vellum` becomes `#221E17` with an `oak`-tinted hairline so the "paper note" reading survives.

### 2.4 The AI material — «пометка на полях»

Machine-written content must never be visually confusable with data the state published. Both appear in the same card, sometimes in the same sentence.

Every LLM output — the judge's verdict, the digest text, the compiled filter's rationale, the recommendation explanation — is rendered on **vellum**: `background: var(--vellum)`, `border: 1px solid #E9DFC9`, `border-radius: 10px`, and a 3px `oak` bar down the left edge. Above it, a small uppercase mono eyebrow with the model source, e.g. `ИИ-ВЕРДИКТ · qwen3.6-35b`. Official data stays on white with `n-100` hairlines.

The reading is: *a note someone pinned in the margin of the official document.* Warm paper against cool official white. This is the primary carrier of "office warmth" and it earns its place by doing real semantic work.

Rules:
- Nothing on vellum is ever presented as fact without a citation control (§8.5) or an explicit «модель не нашла подтверждения».
- Vellum never appears for data that came from ЕИС.
- Do not add a robot/sparkle icon. The material is the signal.

### 2.5 Typography

Three roles, all with complete Cyrillic.

| Role | Face | Usage |
|---|---|---|
| UI + headings | **Golos Text** (Paratype, open) 400/500/600/700 | this is the Госуслуги lineage — headings, buttons, labels, body |
| Long-form reading | **Golos Text** 400, `line-height: 1.6`, `max-width: 68ch` | digest text, document viewer, verdict bodies |
| Data | **JetBrains Mono** 400/500 | reestr numbers, ИНН/КПП, ОКПД2, message_id, SQL preview, money in tables |

Self-host as subset woff2 (Cyrillic + Latin + digits), `font-display: swap`, preload the two most used weights. No Google Fonts CDN — the deployment may be network-restricted, same reasoning as the vendored root certificate.

Scale (base 16px, tight tracking on the large end — Golos Text loosens visually as it grows):

```
display  34/40  600  -0.02em   page titles on digest only
h1       26/32  600  -0.015em  page titles
h2       20/28  600  -0.01em   section headings, tender name in card header
h3       16/24  600  0         subsection, card titles
body     15/22  400  0         default
body-sm  13/20  400  0         table cells, meta rows
caption  12/16  500  0.02em    labels, eyebrows, pills
mono     13/20  400  0         codes; mono eyebrows: 11/16 500 uppercase 0.06em
```

Numeric discipline: `font-variant-numeric: tabular-nums` on every column of money, dates, counts. Money and dates never reflow between rows.

### 2.6 Layout, spacing, shape

- **Base unit 4px.** Spacing scale: 4, 8, 12, 16, 20, 24, 32, 40, 56, 72. Nothing off-scale.
- **Radii:** 6 (inputs, pills), 10 (cards, vellum), 14 (modals, drawers, popovers), 999 (status pills, avatars). No zero-radius surfaces — the institution is friendly here.
- **Elevation:** only three. Flat (hairline only) → hover `0 1px 2px rgb(18 21 26 / 0.04), 0 4px 12px rgb(18 21 26 / 0.06)` → overlay `0 12px 32px rgb(18 21 26 / 0.12)`. No coloured shadows.
- **Shell:** persistent left rail 248px (collapsible to 64px, state persisted), sticky top bar 56px, content region `max-width: 1440px` with 32px gutters, and a right **inspector panel** 480px that slides over the list without unmounting it (§7.3). Below 1280px the inspector becomes a full-screen sheet; below 900px the rail becomes a bottom bar of five items.
- Content areas breathe: 24px card padding, 32px between sections, 12px between related controls.

### 2.7 The signature: «Шкала сроков» (deadline rail)

**One memorable element, and it comes straight from a backend constraint.** ЕИС does not send `purchaseStatus`; status is derived from dates. So instead of pretending a status exists, the interface renders the dates themselves as a small horizontal rail that appears at three scales:

```
 публикация        окончание подачи     работа комиссии        итоги
     ●━━━━━━━━━━━━━━━━━━━━●───────────────────○ ─ ─ ─ ─ ─ ─ ─ ─○
                     ▲ сейчас
```

- **Micro (list row, 120×20px):** a 2px track, filled `gos` up to today, `n-200` after; a 6px `ink` "now" tick; deadline node turns `oak` when < 72h remain and `signal` when passed. Renders as an SVG, no text.
- **Meso (inspector, 100%×48px):** the same rail with four labelled nodes and the remaining time in words.
- **Macro (tender page header, 100%×88px):** full rail with dates under each node, a hover tooltip per node, and — when the crawler observed a date change — a ghost node at the old position connected by a dotted line, labelled «срок сдвинут на 5 дней». Shifted deadlines are already a digest topic; this is where they become visible.

The rail is the thing the analyst learns to read at a glance. Everything around it stays quiet.

**Ambient motion, one place only:** the "now" tick has a 2px vertical hairline that fades in on hover across all visible rails simultaneously, aligning them to the same today-line. 160ms, disabled under `prefers-reduced-motion`. No other ambient animation anywhere in the app.

### 2.8 Motion

- Durations: 120ms (state), 180ms (enter/exit), 240ms (drawer/sheet). Nothing longer.
- Easing: `cubic-bezier(0.2, 0, 0, 1)` for enter, `cubic-bezier(0.4, 0, 1, 1)` for exit.
- One orchestrated moment: on the digest page, sections reveal with a 40ms stagger and 8px rise on first load of the day only (store the date in `localStorage`; do not replay on navigation back).
- `@media (prefers-reduced-motion: reduce)` — all transitions to 1ms, staggers removed, opacity-only.

---

## 3. Stack

```
Next.js 15 (App Router, TypeScript strict, React 19)
Tailwind CSS v4 (@theme inline; tokens in CSS, not in tailwind.config)
Radix UI primitives (dialog, popover, dropdown, tooltip, tabs, toast, select)
TanStack Query v5 + TanStack Virtual
nuqs (all list/filter state lives in the URL)
zod + react-hook-form
date-fns + date-fns/locale/ru
lucide-react (line icons, 1.5px stroke) + hand-authored SVG for the deadline rail
next-themes (light/dark/system)
Recharts — only for the two charts in §5.10; nowhere else
```

Package manager: `pnpm`. Node 20+.

**Do not add:** a component library with its own visual opinion (MUI, AntD, Chakra), a state manager beyond Query + URL, a charting lib beyond Recharts, an animation lib (CSS transitions are enough; if you truly need spring physics for the inspector, `motion` is permitted for that one component and nothing else).

---

## 4. Project structure

The backend enforces strict layering with `lint-imports`. Mirror that discipline on the client — it is the same team and the same rule.

```
src/
  app/                      Next routes only: page.tsx, layout.tsx, loading.tsx, error.tsx
  widgets/                  composed page blocks (TenderList, DigestReader, FilterBuilder, ServiceHealthGrid)
  features/                 user actions with side effects (rate-tender, compile-filter, run-judge, export-csv)
  entities/                 domain models + their presentational atoms (tender, document, filter, digest, profile, run)
  shared/
    api/                    generated OpenAPI types + fetch client + query keys
    ui/                     design-system primitives (Button, Card, Pill, Table, Field, Rail, VellumNote…)
    lib/                    formatters, hooks, constants
    i18n/ru.ts              every user-visible string
```

Enforce with `eslint-plugin-boundaries`: `app → widgets → features → entities → shared`. Imports never go up or sideways across slices. Add `pnpm lint:boundaries` to CI, exactly parallel to `lint-imports`.

---

## 5. Routes — every page, in build order

Russian labels are the actual UI strings. Take them literally; they live in `shared/i18n/ru.ts`.

### 5.0 Route map

| Route | Title (RU) | Purpose |
|---|---|---|
| `/` | Сводка дня | today's digest, the landing surface |
| `/digest/[date]` | Сводка за 6 августа | archived digest |
| `/tenders` | Каталог закупок | the main working list |
| `/tenders/[id]` | Карточка закупки | full notice, tabs |
| `/tenders/[id]/documents/[docId]` | Документ | text/OCR viewer with fragment highlighting |
| `/tenders/compare` | Сравнение | 2–4 tenders side by side |
| `/search` | Поиск по документам | full-text + semantic over document chunks |
| `/filters` | Фильтры | saved filters |
| `/filters/new`, `/filters/[id]` | Конструктор фильтра | build / edit / test |
| `/recommendations` | Рекомендации | ranked feed with explanations |
| `/profile` | Профиль интересов | weights, rating history, wins |
| `/monitoring` | Состояние системы | health of all six services |
| `/monitoring/crawler` | Выгрузки из ЕИС | `crawler_runs`, re-run a day |
| `/monitoring/queues` | Очереди и повторы | RabbitMQ, retry ladder, dead-letter |
| `/monitoring/documents` | Обработка документов | OCR/chunking pipeline state |
| `/settings` | Настройки | connections, regions, digest schedule, certificate |
| `/help` | Справка | shortcuts, glossary, what the AI does |

Build order: 5.2 → 5.3 → 5.1 → 5.6 → 5.5 → 5.7 → 5.8 → 5.9 → 5.10 → rest.

---

### 5.1 `/` — Сводка дня

The first thing seen every morning. Its job: in 90 seconds, tell the analyst whether today needs their attention.

The opener is **not** a stat card row. It is the digest itself, set as a document — because the digest is the most characteristic artifact this system produces.

```
┌────────────────────────────────────────────────────────────┐
│ четверг, 6 августа                          [Печать] [⋯]   │
│                                                             │
│ Сводка дня                              ← display, 34px     │
│ 214 извещений · 12 по вашим фильтрам · 3 срока истекают     │
│ ─────────────────────────────────────────────────────────── │
│ ┃ ИИ-СВОДКА · qwen3.6-35b                    (vellum note)  │
│ ┃ Основной объём дня — поставки медицинского               │
│ ┃ оборудования по Северо-Западу…                            │
│ ┃                            [Как собрана сводка ▾]         │
│ ─────────────────────────────────────────────────────────── │
│ Крупнейшие закупки            ← h2                          │
│ [tender row] [tender row] [tender row]                      │
│                                                             │
│ Новые заказчики               [3]                           │
│ [customer row with first-seen date + tender count]          │
│                                                             │
│ Сдвинутые сроки               [5]                           │
│ [row with macro deadline rail showing the ghost node]       │
│                                                             │
│ По вашим фильтрам             [12]                          │
│ [grouped by filter name, collapsible]                       │
└────────────────────────────────────────────────────────────┘
```

Details:
- Sections come from the map-reduce output. Render only the sections the backend returned; never show an empty section with «нет данных».
- «Как собрана сводка» expands to the per-category summaries (the map step) — the reduce step's inputs. This is how a machine summary earns trust.
- The date is a control: a compact calendar popover with dots on dates that have digests. Left/right arrow keys move day by day.
- If today's digest has not been generated yet: a vellum note reading «Сводка за сегодня ещё не собрана. Обычно готова к 08:30.» with a `[Собрать сейчас]` button that POSTs `digest.requested` and switches to a live pending state (§9.5).
- If the crawl for the date failed: a `signal`-bordered banner *above* the digest — «Выгрузка за 6 августа завершилась с ошибкой (код 34): организация заблокирована в личном кабинете ЕИС.» + `[Открыть выгрузки]`.
- Empty but successful crawl: informational, not alarming — «За 6 августа публикаций по вашим регионам нет. Это не ошибка: за конкретный день их могло не быть.» + `[Проверить за три дня]` which re-queries with `days_back=3`.
- First-load stagger animation (§2.8), once per calendar day.
- Print stylesheet: the digest prints as a clean one-column memo, rails and buttons removed, URLs of tenders as footnotes.

### 5.2 `/tenders` — Каталог закупок

The workbench. Build this first; most other pages reuse its parts.

```
┌ rail ┬──────────────────────────────────────────┬ inspector ─┐
│      │ [🔎 Опишите, что ищете, обычным языком ] │            │
│      │  ─ или ─  [Фильтры ▾][Регион ▾][Цена ▾]  │  (§7.3)    │
│      │ ┌──────────────────────────────────────┐ │            │
│      │ │ активные условия как чипы  [×][×][×] │ │            │
│      │ │ Найдено 1 248 · Сохранить как фильтр │ │            │
│      │ └──────────────────────────────────────┘ │            │
│      │ ┌──────────────────────────────────────┐ │            │
│      │ │ ▸ row  ▸ row  ▸ row  … (virtualized) │ │            │
│      │ └──────────────────────────────────────┘ │            │
└──────┴──────────────────────────────────────────┴────────────┘
```

**Search bar.** One field, two modes, no mode switch: the analyst types Russian prose, presses Enter, and the client POSTs `/filters/compile`. The compiled result renders **as editable chips** — structured conditions as blue chips, the semantic query as a quoted chip, the LLM criterion as a small vellum chip. So the machine's interpretation is never hidden, and every part of it is removable with one click. This is the answer to "AI search you can trust": show the compilation, let them edit it.

If the compile returns an empty `llm_criteria` on a simple query, that is normal — show nothing extra. If it returns empty `llm_criteria` **and** `keywords` that are just the query tokenised, that is the degraded fallback — surface the banner from §9.6.

**Row anatomy** (72px tall, 3 lines, hairline separated, whole row is a link, hover raises to elevation-1):

```
┌────────────────────────────────────────────────────────────────────┐
│ [pill Приём заявок]  ГБУЗ «Городская больница №4»      2 450 000 ₽ │
│ Поставка расходных материалов для лабораторной диагностики…        │
│ 0372200012345000123 · ОКПД2 32.50.50 · Санкт-Петербург  ▁▁▂▂●──○   │
└────────────────────────────────────────────────────────────────────┘
```

- Price right-aligned, tabular mono, `₽` after a non-breaking space.
- Reestr number and ОКПД2 in mono `n-600`; click copies with a toast «Номер скопирован».
- Micro deadline rail at the right of line 3.
- Row-level actions appear on hover/focus at the right edge, never permanently: `[В избранное] [Скрыть] [Похожие]`. Keyboard: `f`, `h`, `s` on the focused row.
- A row matched by an LLM criterion gets a 3px `oak` left edge — the same material language as the vellum note, at row scale. Hovering it shows the verdict snippet in a tooltip.

**Filters.** Left of the list on ≥1600px as a persistent 280px column; below that, a popover per facet. Facets: заказчик, регион, цена (range with histogram of the current result set), ОКПД2 (tree, searchable), дата публикации, срок подачи, способ определения поставщика, наличие документов, «есть распознанный текст». Every applied filter is a removable chip. `Ctrl+K` opens the command palette; `/` focuses search.

**State in the URL.** Every facet, the sort, the page cursor, and the inspector's open tender id are query params via `nuqs`. A pasted URL reproduces the exact screen. This is non-negotiable — the analyst sends links to colleagues.

**Sorting:** по релевантности (default when a query is present), по цене, по сроку подачи, по дате публикации. Sort control is a segmented control, not a select.

**Bulk:** checkbox column appears on `Shift`-click or on hovering the row number gutter. Selected → sticky bottom bar: `Выбрано 4` · `[Сравнить] [Экспорт в CSV] [Скрыть все]`.

**Virtualization** above 60 rows; cursor pagination with an intersection-observer «Показать ещё 50» that also auto-loads once, then requires a click (never infinite-scroll a list someone must be able to leave and return to).

**Empty states**, all with an action:
- no results: «Ничего не найдено. Попробуйте убрать условие "цена до 500 000 ₽" — оно отсекает 80% выдачи.» (compute which single chip is most restrictive and name it).
- no data at all: «Каталог пуст. Запустите выгрузку за вчера.» + `[Запустить выгрузку]`.

### 5.3 `/tenders/[id]` — Карточка закупки

```
┌────────────────────────────────────────────────────────────────┐
│ ← Каталог                       [В избранное] [Скрыть] [Печать]│
│ [pill]  Поставка расходных материалов…            ← h1 (2 lines max) │
│ 0372200012345000123 · опубликовано 04.08.2026 · 44-ФЗ          │
│                                                                 │
│ ═══ macro deadline rail, 88px, with ghost node if shifted ═══   │
│                                                                 │
│ [Обзор] [Документы 7] [ИИ-анализ] [Похожие] [События]           │
│ ───────────────────────────────────────────────────────────────│
│                                          │  right column 320px  │
│  tab content                             │  Начальная цена      │
│                                          │  2 450 000,00 ₽      │
│                                          │  Обеспечение заявки  │
│                                          │  Заказчик, ИНН, КПП  │
│                                          │  Площадка ↗          │
│                                          │  [Открыть на ЕИС ↗]  │
└────────────────────────────────────────────────────────────────┘
```

**Обзор:** объект закупки, способ определения поставщика, place of delivery, terms, обеспечение, комиссия dates. Rendered as a definition list — label `caption` in `n-600`, value `body` in `ink`, two columns on wide. Money in mono. Any field absent from ЕИС renders as an em-dash with a tooltip «Не передаётся в извещении», never as an empty row.

**Документы:** table of attachments — name, type, size, OCR status pill (`Распознан` / `В обработке` / `Не распознан` / `Ошибка`), chunk count. Row → the viewer (§5.4). A file whose text extraction failed shows `[Повторить распознавание]`. If `docs-worker` has not touched the tender yet, show a pending row with the queue position rather than an empty table.

**ИИ-анализ:** the judge's work, on vellum. For each active criterion:

```
┃ ИИ-ВЕРДИКТ · qwen3.6-35b · reasoning: low
┃ Критерий: «гарантия не менее 3 лет»
┃ ✓ Подходит — уверенность высокая
┃ В ТЗ указан гарантийный срок 36 месяцев с даты поставки.
┃ [Показать источник ↗]  ← jumps to the fragment in the document viewer
```

Verdict states: `Подходит` (moss check) / `Не подходит` (signal) / `Не удалось определить` (n-400) — the third is a first-class state with the explanation «В документах нет данных по этому критерию», never a silent absence. `[Проверить заново]` re-runs the judge and shows the async pending pattern (§9.5). If no criterion has been evaluated: «Судья не запускался: структурных условий было достаточно.» — this is the normal, cheap path and must not read like a failure.

**Похожие:** ANN neighbours, 6 cards, each with a cosine-similarity bar and the one field that drove similarity («совпадает ОКПД2 и формулировка объекта»).

**События:** the tender's event trail — `tender.ingested`, `document.extracted`, `tender.enriched`, `embedding.requested` — with timestamps, `message_id` in mono, and retry attempts as a numbered ladder (numbering here is real: 5с → 30с → 2м → 10м → 1ч). Failed → dead-letter is a `signal` terminal node with `[Повторить]`.

**Feedback strip**, fixed to the bottom of the content column on all tabs:
`Полезно?` `[👍 Да] [👎 Нет] [Скрыть похожие]` `[Отметить победу]`
Optimistic, with undo in the toast for 6 seconds. Every rating POSTs `feedback.recorded` and immediately updates the local profile weights preview in the toast: «Учтено: +ОКПД2 32.50, +Санкт-Петербург».

### 5.4 `/tenders/[id]/documents/[docId]` — Документ

Two-pane: extracted text (68ch measure, `Golos Text` 15/26) on the left, a thin outline of chunk boundaries on the right. Deep-linkable to a chunk: `#chunk-42`. Arriving from a verdict citation scrolls to and highlights the fragment with a 600ms `oak` wash that settles into a persistent `oak-tint` background.

- Search within the document (`Ctrl+F` intercepted) with match count and next/prev.
- Header shows the source: original filename, size, MinIO object key in mono, `[Скачать оригинал]`.
- If OCR: badge «Распознано OCR» + «Возможны ошибки распознавания» in `n-600`, and a `[Показать исходную страницу]` toggle if page images exist.
- Highlighting is done from server-provided offsets when available; otherwise client-side over escaped text. Never `dangerouslySetInnerHTML` with server text — build the highlight as React nodes from offsets.

### 5.5 `/search` — Поиск по документам

Different job from the catalog: here the unit of result is a **fragment**, not a tender.

- One query field, plus a two-state control `[По словам] [По смыслу]` and an `[И то, и другое (RRF)]` third state that is the default — naming the actual retrieval strategy, because this user understands it and benefits from controlling it.
- Results: fragment cards. Each shows ~3 lines of matched text with `<mark>` highlights, the source document name, the tender name and price above it, and the retrieval score breakdown on hover (`лексика 0.42 · вектор 0.31 · RRF 0.0161`). Showing the score decomposition is unusual and exactly right for this audience.
- `[Открыть документ]` and `[Открыть закупку]` on every card.
- `[Сделать из этого фильтр]` converts the current query into a saved filter (§5.6).

### 5.6 `/filters` and `/filters/[id]` — Фильтры

List page: cards, each with name, a plain-language summary of the conditions, match count for the last 7 days as a 7-bar sparkline, last-run timestamp, and toggles `Включён в сводку` / `Уведомлять`. Actions: `[Открыть]` `[Дублировать]` `[Удалить]`.

Builder page — three stacked panels, in the order the pipeline actually runs:

```
1. Структурные условия      ← rows: [поле ▾][оператор ▾][значение]   cheap, SQL
   ┌ SQL-предпросмотр ▾  (mono, read-only, syntax-tinted)
2. Семантический запрос     ← textarea + «похоже на»: 3 sample fragments live-previewed
3. Критерий для ИИ-судьи    ← vellum textarea, with cost note:
   «Судья читает документы кандидатов. ~40 закупок в день ≈ 2 минуты работы модели.»
```

Below: `[Проверить фильтр]` runs against the last 30 days and shows, side by side, **сколько отсеял каждый этап**:

```
Все за 30 дней        4 812  ████████████████████
После структурных       318  ██
После семантики          96  ▊
После судьи              41  ▎
```

This funnel is the single most useful thing on the page — it makes an opaque three-stage pipeline legible and is how a user learns whether their criterion is too tight. Clicking any bar shows the items dropped at that stage.

Free-text entry at the top: «Опишите фильтр словами» → `/filters/compile` → fills all three panels, each field marked `изменено моделью` until touched. `[Начать заново]` clears.

### 5.7 `/recommendations` — Рекомендации

- Feed of tender cards, richer than catalog rows: name, price, deadline rail, and an **explanation row** that is always present:
  `Почему здесь: ОКПД2 32.50 (вес 0.34) · регион СПб (0.21) · похоже на выигранную «Поставка реагентов» (0.18)`
  Rendered as small weighted chips whose width is proportional to contribution. Data shape must tolerate a non-linear ranker later: `{ factor: string, label: string, contribution: number }[]` — the component reads `contribution` only for relative sizing and never claims the factors sum to the score.
- **Exploration items are labelled**, not hidden: a `caption` eyebrow «Для расширения кругозора» and a dotted top border. Sidebar note: «15% выдачи — закупки за пределами вашего профиля. Оцените их, чтобы профиль стал точнее.» Being honest about the exploration slice is what makes a user rate it instead of dismissing the feed as broken.
- Per-card feedback with the same optimistic pattern as §5.3, and a `[Не показывать такие]` that asks *which part* to down-weight (заказчик / ОКПД2 / регион) rather than silently guessing.
- Cold start (< ~20 ratings): the feed is replaced by an onboarding block — «Профиль ещё пуст. Оцените 10 закупок, и рекомендации станут осмысленными.» with a rating queue of diverse tenders and a `n/10` progress rail.

### 5.8 `/profile` — Профиль интересов

- **Weights** as a horizontal bar list grouped by facet (ОКПД2, регион, заказчик, ценовой диапазон), each editable by drag or number entry, with `[Сбросить к вычисленному]`. Manual overrides are marked `задано вручную`.
- **History**: table of every rating — closed tender, verdict, date, `[Отменить оценку]`.
- **Wins**: tenders marked as won, with total value. This is the strongest signal the recsys has; give it a real surface, not a checkbox.
- **Ranker status**: «Обученный ранжировщик подключается при ~500 оценках. Сейчас 137.» with a progress rail. Honest, and it explains why the ranking is linear today.

### 5.9 `/monitoring` — Состояние системы

Six service tiles in a 3×2 grid; each tile: name, port, status dot (moss/oak/signal), p95 latency, and one service-specific fact:

- `api` — RPS, error rate
- `crawler` — last successful run, tenders saved today
- `docs-worker` — queue depth, documents pending OCR
- `embedding-service` — **`device: mps | cuda | cpu`**, read from `/health/ready`, with the note «На Apple Silicon в контейнере доступен только CPU» when `device=cpu` and the host looks like macOS. This is a real, documented footgun; surface it.
- `llm-service` — model, `reasoning_effort` per task, whether `json_schema` fell back to `json_object` (show as a badge «схема в промпте» — the client discovers this on first refusal and never retries strict mode; make that visible so nobody debugs it twice)
- `recsys-service` — profile size, last rebuild

Below: a queue table (queue, depth, consumers, dead-letter count) and, if any dead-letter is non-zero, a `signal` block listing the failed messages with `message_id`, error, retry stage, and `[Повторить]`.

**`/monitoring/crawler`**: `crawler_runs` as a table — `target_date`, `status`, `fetched`, `saved`, `error_message`. Failed rows expand to show the raw `dataInfo/errorInfo` payload in mono. Known codes get a plain-language line: code `34` → «Организация заблокирована в личном кабинете ЕИС. Нужен действующий токен.» A date picker + `[Выгрузить заново]` runs a single day. A calendar heatmap of the last 60 days (published counts, grey = no run) makes gaps obvious at a glance.

**`/monitoring/queues`**: the retry ladder drawn as five numbered stages (5с → 30с → 2м → 10м → 1ч) → dead-letter, with live counts on each stage. Numbering is legitimate here: it is a real ordered sequence.

**`/monitoring/documents`**: pipeline funnel — вложений скачано → текст извлечён → OCR → чанков создано → эмбеддингов построено, with failure counts clickable into a filtered list.

### 5.10 `/settings` — Настройки

Read-mostly, because configuration lives in `.env`. Show the effective config with values masked, and make clear what requires a restart.

- **Подключение к модели**: base URL, model URI, auth scheme, reasoning effort per task. `[Проверить связь]` runs the documented probe — `POST /filters/compile` with «поставка ламп с гарантией не менее 3 лет» — and reports pass/fail with the exact diagnostic: непустой `llm_criteria` ⇒ ok; пустой + tokenised keywords ⇒ «модель недоступна, работает деградированный режим». Show the raw response in a collapsible mono block.
- **Регионы и категории** for the crawler, **расписание сводки** (time picker, default 08:30).
- **Сертификат ЕИС**: subject, fingerprint, «действителен до 27.02.2032» with a `oak` warning inside 90 days and a copy-ready update URL.
- **Токен ЕИС**: masked, with a persistent `signal` note if the deployment predates the secret rotation — «Прежний токен лежал в открытом виде в репозитории. Перевыпустите его в личном кабинете ЕИС.» Dismissible only by an explicit `[Токен перевыпущен]` confirmation stored server-side.
- **Экспорт**: CSV/XLSX of the current catalog query.

### 5.11 `/help`

Keyboard shortcut table, a glossary (ЕИС, ОКПД2, НМЦК, РРФ/RRF, эмбеддинг, чанк), and a plain-language page «Что делает ИИ и чего не делает» — three paragraphs: what the retrieval does, what the judge does, and the explicit statement that the verdict is advisory and every conclusion links to a source fragment.

---

## 6. Design code

### 6.1 `src/app/globals.css`

```css
@import "tailwindcss";

@theme inline {
  /* palette */
  --color-gos: #0d4cd3;
  --color-gos-press: #0a3ca8;
  --color-gos-tint: #e8eefc;
  --color-oak: #b5751a;
  --color-oak-tint: #f7eedd;
  --color-moss: #2e7355;
  --color-moss-tint: #e5f0ea;
  --color-signal: #d22d3d;
  --color-signal-tint: #fbe9ea;
  --color-vellum: #fbf7ef;
  --color-vellum-edge: #e9dfc9;

  --color-n-0: #ffffff;
  --color-n-25: #fafaf8;
  --color-n-50: #f2f3f0;
  --color-n-100: #e7e9e4;
  --color-n-200: #d2d6ce;
  --color-n-400: #8d948b;
  --color-n-600: #5a615a;
  --color-n-900: #12151a;

  /* semantic */
  --color-canvas: var(--color-n-50);
  --color-surface: var(--color-n-0);
  --color-hairline: var(--color-n-100);
  --color-text: var(--color-n-900);
  --color-text-muted: var(--color-n-600);
  --color-text-subtle: var(--color-n-400);

  /* type */
  --font-sans: "Golos Text", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, "SF Mono", monospace;

  --text-display: 2.125rem;   --text-display--line-height: 2.5rem;
  --text-h1: 1.625rem;        --text-h1--line-height: 2rem;
  --text-h2: 1.25rem;         --text-h2--line-height: 1.75rem;
  --text-h3: 1rem;            --text-h3--line-height: 1.5rem;
  --text-body: 0.9375rem;     --text-body--line-height: 1.375rem;
  --text-body-sm: 0.8125rem;  --text-body-sm--line-height: 1.25rem;
  --text-caption: 0.75rem;    --text-caption--line-height: 1rem;

  /* shape & depth */
  --radius-input: 6px;
  --radius-card: 10px;
  --radius-overlay: 14px;
  --shadow-raise: 0 1px 2px rgb(18 21 26 / 0.04), 0 4px 12px rgb(18 21 26 / 0.06);
  --shadow-overlay: 0 12px 32px rgb(18 21 26 / 0.12);

  /* motion */
  --ease-enter: cubic-bezier(0.2, 0, 0, 1);
  --ease-exit: cubic-bezier(0.4, 0, 1, 1);
  --dur-state: 120ms;
  --dur-move: 180ms;
  --dur-panel: 240ms;
}

[data-theme="dark"] {
  --color-canvas: #14161a;
  --color-surface: #1b1e23;
  --color-hairline: #282c32;
  --color-text: #e8eae6;
  --color-text-muted: #a0a69e;
  --color-text-subtle: #757b74;
  --color-gos: #5b8def;
  --color-gos-tint: #17243d;
  --color-vellum: #221e17;
  --color-vellum-edge: #3a3123;
}

@layer base {
  html { -webkit-text-size-adjust: 100%; }
  body {
    background: var(--color-canvas);
    color: var(--color-text);
    font-family: var(--font-sans);
    font-size: var(--text-body);
    line-height: var(--text-body--line-height);
    font-feature-settings: "ss01";
  }
  :focus-visible {
    outline: 2px solid var(--color-gos);
    outline-offset: 2px;
    border-radius: 4px;
  }
  .tnum { font-variant-numeric: tabular-nums; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 1ms !important;
    transition-duration: 1ms !important;
    scroll-behavior: auto !important;
  }
}
```

### 6.2 Primitive recipes

Implement these in `shared/ui/`. Use `cva` for variants. Keep them dumb — no data fetching, no i18n lookups inside.

```
Button      variants: primary (gos, white text) | secondary (surface + hairline)
                    | ghost (transparent, hover n-25) | danger (signal)
            sizes:    sm 32px | md 40px | lg 48px, radius 6, 12/16px padding
            states:   hover darkens 6%, active darkens 12% + translateY(0.5px),
                      disabled 40% opacity no pointer events,
                      loading = label stays, 14px spinner replaces the icon slot
                      (never collapse the button width — layout must not jump)

Pill        status pills, always tint bg + full-saturation text + 999 radius,
            11px caption uppercase 0.04em, 6/10px padding.
            Приём заявок→gos · Работа комиссии→oak · Завершена→n-400
            · Отменена→signal · Опубликована→moss

Card        surface, radius 10, 1px hairline, 24px padding, shadow-raise on hover
            only when the card is a link

VellumNote  the §2.4 material. Props: eyebrow, children, source, actions.
            Always renders the eyebrow. Never renders without a source string.

Rail        the §2.7 deadline rail. Props: { published, deadline, commission,
            summing }, scale: 'micro' | 'meso' | 'macro', previousDeadline?
            Pure SVG, no external deps, aria-label with the full text version.

Table       header 12px caption n-600 uppercase, sticky; rows 48px; hairline
            between rows only (never a full grid); numeric columns right + tnum;
            row hover n-25; NO zebra striping (it fights the hairlines)

Field       label above (caption, n-600), 40px control, 6px radius, 1px n-200
            border, focus = gos border + 3px gos/12% ring, error = signal border
            + message below in body-sm

EmptyState  icon 32px n-200, h3 title, body-sm n-600 explanation (says what to
            do next), one primary action. Never a shrug or an apology.

Skeleton    n-100 blocks with a 1.4s shimmer, shaped exactly like the content
            they replace (row skeletons have the three-line row geometry).
            No spinners anywhere except inside buttons.
```

### 6.3 Icon and illustration policy

`lucide-react`, 1.5px stroke, 18px in rows, 20px in nav, 24px in headers. Where a domain concept has no good lucide match (deadline rail, retry ladder, chunk boundaries) hand-author a 24×24 SVG on the same 1.5px grid. No illustration library, no 3D, no mascot. Empty states use a single line icon, not a scene.

---

## 7. Interaction details

### 7.1 Keyboard

| Key | Action |
|---|---|
| `Ctrl/⌘ K` | command palette (navigate, run filter, open tender by reestr number) |
| `/` | focus search |
| `j` / `k` | next / previous row |
| `Enter` | open focused row in the inspector |
| `Shift+Enter` | open in a new tab |
| `f` / `h` / `s` | favourite / hide / similar, on the focused row |
| `1…5` | switch tabs on the tender page |
| `g` then `d/c/f/r/m` | go to сводка / каталог / фильтры / рекомендации / мониторинг |
| `Esc` | close inspector, then modal, then clear search |

Show the shortcut in every tooltip. `?` opens the shortcut sheet.

### 7.2 Command palette

Fuzzy over: routes, saved filters, recent tenders, and — if the input matches `^\d{19}$` — a direct reestr-number lookup as the first result. Sections labelled, arrow-navigable, `Ctrl+Enter` opens in a new tab.

### 7.3 Inspector panel

Opening a row from the catalog slides in a 480px panel: header (status pill, name, price), meso rail, key facts, the top AI verdict if present, and `[Открыть полностью]`. The list behind it does not unmount, does not scroll, does not lose selection. `j`/`k` moves through rows with the panel open, updating its contents — this is how the analyst triages a hundred notices without a single page load.

### 7.4 Async LLM operations

Judge runs, digest generation, and filter test runs take seconds to minutes. Pattern for all of them:

1. Optimistic pending state appears immediately, in place, with the operation named: «Судья читает документы… обычно 20–40 секунд».
2. Poll with backoff (1s → 2s → 5s, cap 5s) or consume SSE if the endpoint offers it.
3. On success, the result replaces the pending block with a 180ms cross-fade, and `aria-live="polite"` announces «Проверка завершена: подходит».
4. On failure, the pending block becomes an inline error with the reason and `[Повторить]`. Never a toast for a failure the user is watching.
5. Navigating away and back resumes the poll from the task id in the query cache.

### 7.5 Toasts

Bottom-left, max 3 stacked, 6s, with `[Отменить]` where the action is reversible. Reserved for actions whose result is off-screen. Never used for validation errors or for anything the user is looking at.

---

## 8. Domain formatting rules

### 8.1 Numbers, money, dates

```ts
// shared/lib/format.ts
export const money = (v: number) =>
  new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB",
    minimumFractionDigits: 2 }).format(v);          // 2 450 000,00 ₽

export const compactMoney = (v: number) =>          // list rows only
  v >= 1e9 ? `${(v / 1e9).toFixed(1).replace(".", ",")} млрд ₽`
: v >= 1e6 ? `${(v / 1e6).toFixed(1).replace(".", ",")} млн ₽`
:            money(v);

export const date = (d: Date) => format(d, "dd.MM.yyyy", { locale: ru });
export const dateLong = (d: Date) => format(d, "d MMMM yyyy", { locale: ru });
```

- Always a non-breaking space before `₽`, `млн`, `%`, and between a number and its unit.
- Plurals via `Intl.PluralRules("ru-RU")`: `закупка / закупки / закупок`, `день / дня / дней`, `документ / документа / документов`. Write one `plural(n, [one, few, many])` helper and use it everywhere; never `n + " закупок"`.
- Relative deadlines: «осталось 3 дня», «остался 1 день», «сегодня до 17:00», «приём завершён 4 августа». Times are Moscow time — label the column «мск» once in the header, not on every row.
- ИНН/КПП/ОГРН and reestr numbers: mono, no grouping (they are identifiers, not numbers), click-to-copy.

### 8.2 Status

One module, `entities/tender/model/status.ts`, computing status from dates with exactly the backend's rule. It returns `{ code, label, tone, source: "computed" }`. Every status pill carries a `title`/tooltip: «Статус вычислен по датам: ЕИС не передаёт его в извещении.» Do not repeat this note in body text — the tooltip is enough, and honesty here costs nothing.

### 8.3 Truncation

Tender names are long and information-dense. Truncate at 2 lines with `-webkit-line-clamp`, never mid-word with an ellipsis at 60 chars. Full name in `title` and in the inspector. Never truncate a price, a date, or an identifier.

### 8.4 Text from documents

Extracted text may be OCR garbage, may contain control characters, may be enormous. Sanitize (strip control chars, normalize whitespace runs, keep paragraph breaks), render in chunks of ≤2000 characters with virtualization above 50 chunks, and always render as React text nodes — never as HTML.

### 8.5 Citations

Every LLM claim carries a `[Показать источник]` control resolving to `{ documentId, chunkId, charStart, charEnd }`. If the backend returns a claim without a resolvable citation, render the claim with a `n-400` marker «источник не указан» rather than dropping it or presenting it as verified. This rule is the backbone of the product's trustworthiness — implement it before implementing anything decorative.

---

## 9. Implementation details

### 9.1 API layer

```bash
pnpm gen:api   # openapi-typescript http://localhost:8000/openapi.json -o src/shared/api/schema.d.ts
```

Never hand-write a DTO. Use `openapi-fetch` with the generated types. If an endpoint you need is missing from the schema, **stop and list it** in `docs/API-GAPS.md` with the exact shape you need — do not invent a client-side workaround silently.

Single `apiClient` with: base URL from `NEXT_PUBLIC_API_URL`, a 30s timeout, `AbortSignal` wiring from Query, an `Idempotency-Key` header (uuid v4) on every POST that records feedback or enqueues a job, and an auth interceptor that is present but reads a null token today (§9.10).

### 9.2 Query keys and caching

```ts
export const qk = {
  tenders: {
    list: (params: TenderQuery) => ["tenders", "list", params] as const,
    byId: (id: string) => ["tenders", "detail", id] as const,
    similar: (id: string) => ["tenders", "similar", id] as const,
    events: (id: string) => ["tenders", "events", id] as const,
  },
  documents: { byTender: (id: string) => ["docs", id] as const,
               text: (id: string) => ["docs", "text", id] as const },
  filters: { all: ["filters"] as const, byId: (id: string) => ["filters", id] as const,
             compile: (q: string) => ["filters", "compile", q] as const },
  digest: (date: string) => ["digest", date] as const,
  recs: (cursor?: string) => ["recs", cursor ?? "first"] as const,
  profile: ["profile"] as const,
  health: ["health"] as const,
  crawlerRuns: (limit: number) => ["crawler", "runs", limit] as const,
};
```

`staleTime`: tender detail 5 min · list 60 s · document text `Infinity` · digest `Infinity` for past dates, 60 s for today · health 15 s with `refetchInterval` 15 s only while `/monitoring` is mounted · profile 30 s.

Invalidate narrowly: a feedback POST invalidates `profile` and `recs`, never `tenders`.

### 9.3 URL state

`nuqs` parsers for every list param, with defaults that serialize to nothing (a clean `/tenders` URL when nothing is applied). Array params as comma-joined. The inspector's open tender is `?preview=<id>`. Debounce the search input into the URL at 400ms but into the query at 400ms too — never fire a request per keystroke.

### 9.4 Virtualization and pagination

`@tanstack/react-virtual` with `estimateSize: 72` and `overscan: 8`. Rows must be fixed-height — do not let a long name grow a row; that is what the 2-line clamp is for. Cursor pagination; keep the scroll anchor when the next page arrives.

### 9.5 Optimistic mutations

Feedback, favourites, hide, and filter toggles are optimistic with rollback. Pattern: `onMutate` cancels in-flight queries for the key, snapshots, writes the optimistic value; `onError` restores and shows an inline error (not a toast) if the affected element is visible; `onSettled` invalidates. The undo action in the toast issues the inverse mutation, not a cache edit.

### 9.6 Degraded-mode detection

```ts
// features/compile-filter/lib/detect-degraded.ts
export function isDegraded(query: string, r: CompileResult): boolean {
  if (r.llm_criteria?.length) return false;
  const tokens = query.toLowerCase().split(/\s+/).filter((t) => t.length > 2);
  const kw = (r.keywords ?? []).map((k) => k.toLowerCase());
  const overlap = tokens.filter((t) => kw.includes(t)).length;
  return tokens.length >= 3 && overlap / tokens.length > 0.8;
}
```

When true, mount a global `oak`-bordered banner under the top bar: «ИИ-фильтрация недоступна: модель не отвечает. Поиск работает по ключевым словам.» + `[Проверить подключение]` → `/settings`. The banner is sticky per session, dismissible, and reappears on the next degraded response. Do **not** show it when `llm_criteria` is empty on a short simple query — that is the normal cheap path.

### 9.7 Error and loading boundaries

Every route gets `loading.tsx` (layout-shaped skeleton) and `error.tsx` (what failed, what to do, `[Повторить]`, and a `[Скопировать детали]` that copies status + endpoint + request id). Errors state facts and next steps; they do not apologise and are never vague. Root `not-found.tsx` and a global error boundary that survives a Query cache corruption.

### 9.8 Accessibility (hard requirement, not a nice-to-have)

- WCAG 2.1 AA contrast for all text including on tints — verify `oak` on `oak-tint` and `n-400` on `n-25` specifically.
- Every interactive element reachable and operable by keyboard; visible `:focus-visible` ring everywhere; a skip-to-content link.
- The deadline rail is decorative SVG with `role="img"` and a full `aria-label`: «Опубликовано 4 августа, приём заявок до 14 августа, осталось 6 дней».
- Async results announced via `aria-live="polite"`; errors via `role="alert"`.
- Tables use real `<table>`/`<th scope>`; the list is a `<ul>` of links, not a div soup.
- Minimum target 40×40px; row hover actions are also focusable in DOM order.
- Colour is never the only status carrier — every pill has a word.

### 9.9 Performance budget

Initial JS ≤ 200 KB gzipped; LCP ≤ 1.8 s on localhost; CLS ≈ 0 (skeletons reserve exact geometry, fonts preloaded, no late-loading banners pushing content). Route-level code splitting; Recharts dynamically imported only on `/monitoring` and `/profile`. Memoize row components; the virtualized list must not re-render on inspector state changes.

### 9.10 Auth-ready, auth-less

Ship no login. But: a `useCurrentProfile()` hook returning the single global profile with its id, a `Bearer` interceptor reading from a `getToken()` that returns `null`, and every profile-scoped query key already containing the profile id. When multi-user arrives, the diff is a login route and a real `getToken()` — nothing else. Do not add a fake user avatar or a fake logout.

### 9.11 Testing

- Vitest + Testing Library for formatters (money, plurals, relative dates), status computation, degraded detection, and the rail's geometry maths.
- MSW handlers generated from the OpenAPI schema; a `docs/fixtures/` set with three realistic tenders (one with OCR-only documents, one with a shifted deadline, one cancelled).
- Playwright, five flows: compile a filter from free text → save it; triage 10 rows with `j`/`k` + inspector; open a verdict → jump to the source fragment; rate a recommendation and see the profile change; open `/monitoring` with a failed crawl and re-run the day.
- A dark-theme visual pass on the catalog, tender card, and digest.

### 9.12 Deliverables

- `README.md` (Russian) — run, env vars, `pnpm gen:api`, how to point at a non-localhost API.
- `docs/DESIGN.md` (Russian) — the token table, the rail spec, the vellum rule, with screenshots.
- `docs/API-GAPS.md` — endpoints the UI needs that the backend does not yet expose.
- `.env.example` with `NEXT_PUBLIC_API_URL=http://localhost:8000`.
- A `docker-compose` service `web` on port `3000`, added alongside the existing stack, replacing `dashboard` in the documented workflow.

---

## 10. Copy

All strings in `shared/i18n/ru.ts`, typed, no string literals in JSX. Rules:

- Sentence case everywhere. No Title Case, no ALL CAPS except mono eyebrows.
- Name things by what the analyst controls, not by how the system is built: «Проверить фильтр», not «Запустить evaluation pipeline». «Обработка документов», not «docs-worker».
- Buttons say what happens: «Сохранить фильтр» → toast «Фильтр сохранён». Same verb through the whole flow.
- Errors state what happened and what to do. «Модель не ответила за 30 секунд. Проверьте LLM_BASE_URL — из контейнера хост доступен как host.docker.internal.» No «Упс», no «Что-то пошло не так», no apologies.
- Empty screens are invitations: «Каталог пуст. Запустите выгрузку за вчера.»
- Never use «ИИ» as a selling word. Use it as a label for provenance: «ИИ-вердикт», «ИИ-сводка».
- Technical terms the audience actually uses stay: ЕИС, ОКПД2, НМЦК, реестровый номер, эмбеддинг, чанк. Explain them once in `/help`, not in tooltips on every screen.

---

## 11. Working method

Follow this order. Do not skip the planning pass.

1. **Plan before code.** Write `docs/DESIGN.md` first: the token table, three ASCII wireframes for `/tenders` (list-only, list+inspector, list+facets+inspector), and the rail spec at all three scales. Then read it back against §2.2 — if any element reads like the default you'd produce for any admin panel, change it and note what you changed and why.
2. **Primitives first.** Build `shared/ui/` with a `/dev/kitchen-sink` route showing every primitive in every state, light and dark. Screenshot it. Critique it. Fix contrast and rhythm there, before any page exists.
3. **Then `/tenders`,** end to end with real API data — row, rail, inspector, facets, URL state, virtualization, empty and error states. This page proves the system.
4. **Then the rest,** in the §5.0 build order.
5. **Critique with screenshots** at each milestone: catalog, tender card, digest, monitoring. Check the mirror — remove one accessory. If a screen has more than one thing competing to be looked at first, quiet everything except the rail.
6. **Responsive and a11y passes** as their own milestone, not as an afterthought: 1920 / 1440 / 1280 / 900 / 390 px, keyboard-only run-through of the five Playwright flows, dark theme.

## 12. Definition of done, per page

- [ ] Loading skeleton matches the final layout's geometry — no layout shift
- [ ] Empty state with an action and a specific explanation
- [ ] Error state naming what failed and what to do
- [ ] Every list/filter state reproducible from the URL
- [ ] Keyboard reachable end to end, visible focus, no traps
- [ ] Dark theme verified
- [ ] Responsive at 1440 / 1280 / 900 / 390
- [ ] All strings from `ru.ts`; correct plurals; ₽ and dates via the formatters
- [ ] Any LLM content on vellum, with an eyebrow and a resolvable citation
- [ ] `prefers-reduced-motion` respected
- [ ] No console warnings, no `any`, `pnpm lint && pnpm typecheck && pnpm lint:boundaries` clean

---

**The bar, in one sentence:** an analyst should open this at 8:30, read the digest, triage the catalog with two keys, act on three tenders, and never once wonder whether the machine is hiding something from them — and it should be a pleasant place to spend the day.
