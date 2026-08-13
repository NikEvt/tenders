# Fix brief — contrast, command entry, timeline labels, catalog sorting

Follow-up to `FRONTEND_BRIEF.md`. The build is good; four defects need fixing. Read the whole file first, then work in the order given — the token work in §1 is a prerequisite for everything else.

**Working rules for this pass:**

- Minimal diffs. Do not rewrite working components, do not reformat untouched files, do not "improve while you're there".
- Every fix lands as a **mechanism**, not as a patch to the symptom. If a fix can only be applied by hand at each call site, you have chosen the wrong fix.
- Layer boundaries stay intact: raw palette and layout maths live in `shared/`, domain vocabulary in `entities/`, composition in `widgets/`. `pnpm lint:boundaries` must stay clean.
- Each of the four sections ships with the regression guard described in it. A fix without a guard is not done.
- Record what changed in `docs/CHANGELOG.md` and update `docs/DESIGN.md` where the design rules themselves change (§1, §2).

---

## 1. Colour: black-on-black in dark theme, black-on-blue everywhere

### 1.1 Root cause — fix this, not the instances

Two structural mistakes, both in the token layer:

1. **Components read the raw ramp.** `--color-n-900` is `#12151A` in *both* themes; it is a palette value, not a semantic one. Any component using `text-n-900` / `bg-n-0` goes black-on-black the moment the canvas darkens. The dark-theme block only ever redefined the semantic aliases.
2. **No foreground token is paired with any coloured background.** Text on `gos`, on the four tints and on vellum inherited `--color-text`, so it followed the theme while the background did not.

Repainting individual components will not hold. Fix the token contract, then make the old spelling unusable.

### 1.2 The contract

Three layers. Components may only reach the third.

| Layer | Example | May change with theme? | Who may use it |
|---|---|---|---|
| Palette | `--palette-blue-600: #0d4cd3` | never | `globals.css` only |
| Semantic | `--color-surface`, `--color-text-muted` | yes | `shared/ui/` and above |
| Pair | `--color-gos-bg` + `--color-on-gos` | yes, together | anywhere |

**Rule: every token that can be a background has a mandatory `--color-on-*` partner, and no component may set a coloured background without also setting its partner as the foreground.** Enforce it by exposing them only as paired utility classes (`.surface-gos`, `.surface-oak-tint`, `.surface-vellum`) that set both properties in one declaration — then it is impossible to take the background without the text colour.

Second rule, less obvious and the source of the black-on-blue: **a colour used as a background and the same colour used as text are different tokens.** The blue that carries white text and the blue that sets a link on the canvas cannot be one value.

### 1.3 Token values

Replace the colour section of `globals.css` with this. Contrast ratios are stated because they must be verified, not trusted.

```css
@theme inline {
  /* ---- palette: never overridden by theme ---- */
  --palette-blue-500: #3b6fe8;
  --palette-blue-600: #0d4cd3;
  --palette-blue-700: #0a3ca8;
  --palette-blue-200: #b9cffb;
  --palette-blue-300: #7fa6f5;
  /* …oak / moss / signal / neutral ramps unchanged, renamed to --palette-* … */

  /* ---- semantic: surfaces & text ---- */
  --color-canvas: var(--palette-n-50);
  --color-surface: var(--palette-n-0);
  --color-surface-raised: var(--palette-n-0);
  --color-hairline: var(--palette-n-100);
  --color-text: var(--palette-n-900);
  --color-text-muted: var(--palette-n-600);
  --color-text-subtle: var(--palette-n-400);

  /* ---- pairs: background + its only legal foreground ---- */
  --color-gos-bg: var(--palette-blue-600);      /* on-gos 7.2:1 */
  --color-on-gos: #ffffff;
  --color-gos-bg-press: var(--palette-blue-700);
  --color-gos-fg: var(--palette-blue-600);      /* blue AS TEXT on canvas, 6.9:1 */

  --color-gos-tint: #e8eefc;
  --color-on-gos-tint: var(--palette-blue-700); /* 8.1:1 — not --color-text */
  --color-oak-tint: #f7eedd;
  --color-on-oak-tint: #7d4f0e;                 /* 6.4:1 */
  --color-moss-tint: #e5f0ea;
  --color-on-moss-tint: #1d4f3a;                /* 7.6:1 */
  --color-signal-tint: #fbe9ea;
  --color-on-signal-tint: #9b1f2c;              /* 6.8:1 */
  --color-vellum: #fbf7ef;
  --color-vellum-edge: #e9dfc9;
  --color-on-vellum: #2a2419;                   /* 13.1:1 */
}

[data-theme="dark"] {
  --color-canvas: #14161a;
  --color-surface: #1b1e23;
  --color-surface-raised: #22262c;
  --color-hairline: #282c32;
  --color-text: #e8eae6;
  --color-text-muted: #a0a69e;
  --color-text-subtle: #757b74;

  --color-gos-bg: var(--palette-blue-500);      /* white on it: 4.6:1 */
  --color-on-gos: #ffffff;                      /* pair holds in both themes */
  --color-gos-bg-press: #2f5cc9;
  --color-gos-fg: var(--palette-blue-300);      /* links on canvas: 7.7:1 */

  --color-gos-tint: #17243d;
  --color-on-gos-tint: var(--palette-blue-200); /* was black on dark blue */
  --color-oak-tint: #2b2113;    --color-on-oak-tint: #e8bd72;
  --color-moss-tint: #14261e;   --color-on-moss-tint: #7fd4a9;
  --color-signal-tint: #2b1518; --color-on-signal-tint: #f2909a;
  --color-vellum: #221e17;      --color-vellum-edge: #3a3123;
  --color-on-vellum: #ded6c6;
}
```

Note on `--color-gos-bg` in dark: the instinct is to *lighten* the accent, and the previous `#5B8DEF` did exactly that — landing at 3.2:1 under white text, too light for white and too dark for black. `#3B6FE8` keeps white legible in both themes, so the primary button's foreground logic never branches on theme. Do not "improve" it upward.

### 1.4 Migration

1. Rename the ramp to `--palette-n-*`. This breaks every direct consumer at compile time — that is the point.
2. Find them: `rg 'n-(0|25|50|100|200|400|600|900)' src/widgets src/features src/entities src/app`
3. Translate each by *intent*, not by value: card background → `surface`, page background → `canvas`, borders → `hairline`, secondary label → `text-muted`, placeholder/disabled → `text-subtle`. If a use site has no matching semantic token, add one — do not reach back into the palette.
4. Audit every coloured background: status pills, verdict banners, the degraded-mode banner, chart series, selected rows, the `oak` left edge on LLM-matched rows, focus rings on tinted surfaces, hover on tinted rows.
5. Charts specifically: Recharts inherits `currentColor` inconsistently. Pass axis, grid, tick and tooltip colours explicitly from semantic tokens; the tooltip surface is `--color-surface-raised` with `--color-text`, never the library default.

### 1.5 Guards

**Lint** — palette off-limits outside the token file:

```js
// eslint.config.js
{
  files: ["src/{app,widgets,features,entities}/**"],
  rules: { "no-restricted-syntax": ["error", {
    selector: "Literal[value=/\\b(bg|text|border|fill|stroke)-n-\\d+\\b/]",
    message: "Raw ramp is not available here. Use a semantic or paired token.",
  }]}
}
```

**Test** — contrast, both themes, in CI:

```ts
// src/shared/ui/__tests__/contrast.test.ts
const PAIRS: [fg: string, bg: string][] = [
  ["--color-text", "--color-canvas"],
  ["--color-text", "--color-surface"],
  ["--color-text-muted", "--color-surface"],
  ["--color-text-subtle", "--color-surface"],   // AA-large / non-text only — assert 3:1
  ["--color-on-gos", "--color-gos-bg"],
  ["--color-on-gos-tint", "--color-gos-tint"],
  ["--color-on-oak-tint", "--color-oak-tint"],
  ["--color-on-moss-tint", "--color-moss-tint"],
  ["--color-on-signal-tint", "--color-signal-tint"],
  ["--color-on-vellum", "--color-vellum"],
  ["--color-gos-fg", "--color-canvas"],
  ["--color-gos-fg", "--color-surface"],
];

describe.each(["light", "dark"] as const)("contrast · %s", (theme) => {
  test.each(PAIRS)("%s on %s ≥ 4.5:1", (fg, bg) => {
    expect(ratio(resolve(theme, fg), resolve(theme, bg))).toBeGreaterThanOrEqual(4.5);
  });
});
```

Parse the tokens out of `globals.css` at test time (a tiny regex reader in `shared/lib/tokens.ts`), so the test fails when someone edits CSS, not when someone remembers to update a duplicate list.

**Visual** — a `/dev/contrast` route rendering every pair as a swatch with its computed ratio, plus every primitive in both themes. Screenshot both, check by eye, keep the screenshots in `docs/`.

---

## 2. Command entry is over-weighted

The `⌘K` button is not too large; it is a *second* wide entry point in the top bar competing with search. Shrinking it leaves two attractors and a weaker bar. Remove the competition instead.

**Change:** delete the standalone button. Move the hint into the search field as a `kbd` chip at the right edge.

```
before:  [🔎 Поиск…              ] [ ⌘K  Быстрый переход ]
after:   [🔎 Опишите, что ищете, обычным языком      ⌘K ]   [⚙]
```

Chip spec: 11px mono, `--color-text-muted`, 1px `--color-hairline`, radius 4, background `--color-surface`, 2/6px padding, `pointer-events: none` by default. If it must be clickable for mouse-only use, make it a `<button variant="ghost">` with a 32×32 hit area inside a 36px box — never `primary`; an accent fill on a secondary action is what caused the imbalance.

Keep the shortcut working exactly as before; this is presentation only. Verify the palette still opens from every route and from inside the inspector.

**Discoverability compensation** (do all three, they are cheap):
- the chip is always visible, not on hover;
- empty search state adds one line: «Или нажмите ⌘K, чтобы перейти к фильтру или закупке»;
- the shortcut table in `/help` stays authoritative.

Below 900px the chip is hidden and the field collapses to an icon button, as now.

**Do not leave a hole.** The freed attention goes to the page's real subject: on `/` the digest title (`display`, 34px), on `/tenders` the result line «Найдено 1 248 · Сохранить как фильтр». Check both at 1440 and 1280 after the change.

---

## 3. Timeline diagrams: overlapping labels

Affects the deadline rail at `meso`/`macro` scale, and any other date-axis visual (crawler heatmap axis, monitoring funnel, digest «сдвинутые сроки»). Fix it once, in `shared/`, and adopt it in all of them.

### 3.1 Why it happens

Four causes, and a fix that misses any one of them will overlap again:

1. Labels are positioned at their node's `x` with `text-anchor: middle` and no collision handling. Real tender dates cluster — publication and deadline can be two days apart on a 60-day rail.
2. Widths are guessed from character counts. Cyrillic in Golos Text does not match those guesses.
3. **Measurement happens before the webfont loads.** With `font-display: swap`, layout is computed against the fallback metrics and never recomputed — this alone explains overlap that appears only after a hard reload.
4. No escalation path: when labels genuinely do not fit, the component keeps trying to draw them inline.

### 3.2 The mechanism

A pure, deterministic, DOM-free layout function. This is the extensibility requirement: the algorithm must be unit-testable without rendering and reusable by any future time axis.

```ts
// src/shared/ui/chart/label-layout.ts
export interface LabelInput {
  id: string;
  x: number;            // ideal position, px, in track space
  text: string;         // full label
  shortText?: string;   // fallback ("работа комиссии" → "комиссия")
  priority: number;     // higher survives when something must be dropped
}

export interface LabelPlacement {
  id: string;
  x: number;                              // resolved centre
  row: 0 | 1;
  anchor: "start" | "middle" | "end";
  text: string;                           // possibly shortText
  leader: boolean;                        // draw a hairline back to the node
}

export interface LayoutOptions {
  width: number;
  padding: number;      // default 4
  gap: number;          // min space between labels, default 8
  maxRows: 1 | 2;       // meso: 1, macro: 2
  maxShift: number;     // px of displacement tolerated before escalating, default 20
  measure: (text: string) => number;      // injected — see 3.3
}

export type LayoutResult =
  | { mode: "inline";  placements: LabelPlacement[] }
  | { mode: "stacked"; placements: LabelPlacement[] }
  | { mode: "legend";  placements: []; items: LabelInput[] };
```

Escalation ladder, in order, stopping at the first that fits:

1. **Single row, full text.** Place each label centred on its node, clamp to `[padding + w/2, width − padding − w/2]`, then resolve collisions with the group-shift sweep below. Accept if no displacement exceeds `maxShift`.
2. **Single row, short text.** Same, using `shortText` where present and a shortened date format (`dd.MM.yyyy` → `dd.MM`).
3. **Two rows** (`maxRows === 2` only). Assign alternating rows by ascending `x`, run the sweep per row independently, row 1 sits 16px below row 0. Any label displaced more than 3px gets `leader: true`.
4. **Legend.** Return `mode: "legend"`; the caller renders the nodes bare and lists the labels underneath as a two-column definition list. Never drop a label silently.

Group-shift sweep (classic minimal-displacement interval packing — deterministic, O(n log n), no iteration cap needed for n ≤ 8):

```
sort by desired x
group = [first]
for each next item:
  if it overlaps the group's right edge (+gap): add to group
  else: flush(group); group = [item]
flush(group)

flush(g):
  total = sum(widths) + gap * (len(g) - 1)
  centre = weighted mean of desired positions
  start = clamp(centre - total/2, padding, width - padding - total)
  lay items out contiguously from start
  if the flush pushed the group into its neighbour, merge and re-flush
```

Anchoring: the leftmost label whose box touches the left pad uses `anchor: "start"`; the rightmost touching the right pad uses `"end"`; everything else `"middle"`. Without this, edge labels overflow the SVG viewBox — a second, separate overlap bug.

### 3.3 Measurement

```ts
// src/shared/ui/chart/measure.ts — canvas-based, cached, font-aware
const cache = new Map<string, number>();
export function makeMeasurer(font: string) {
  return (text: string) => {
    const key = `${font}|${text}`;
    const hit = cache.get(key);
    if (hit !== undefined) return hit;
    ctx.font = font;                       // e.g. "500 12px 'Golos Text'"
    const w = ctx.measureText(text).width;
    cache.set(key, w);
    return w;
  };
}
```

**Recompute after fonts load.** In the rail component:

```ts
const [fontsReady, setFontsReady] = useState(() => document.fonts?.status === "loaded");
useEffect(() => { document.fonts?.ready.then(() => { cache.clear(); setFontsReady(true); }); }, []);
```

`fontsReady` is a layout dependency. Also re-run on container resize via a single shared `ResizeObserver` (`useElementWidth`), debounced to an animation frame. Do not use `getBBox` in a post-render pass — it forces synchronous layout for every rail in a virtualized list of 60 rows.

In tests and SSR, inject a deterministic stub measurer (`text.length * 6.2`) so snapshots are stable.

### 3.4 Component changes

- `Rail` takes the layout result and renders it; it contains no placement maths.
- `micro` scale keeps rendering no labels at all — the fix must not add work to the 60 rails in a list. Guard it: `if (scale === "micro") return null` before any measurement.
- Leader lines: 1px `--color-hairline`, from the node's base to the label's top-centre, drawn under the text.
- The ghost node for a shifted deadline participates in layout like any other node, with lower `priority` so it degrades to `shortText` first.
- `aria-label` is generated from the semantic node list, never from placements — accessibility text is unaffected by mode.
- The tooltip per node stays; in `legend` mode the legend rows are the hover targets.

### 3.5 Guards

```ts
test.each(SCENARIOS)("no overlap: %s", (nodes) => {
  const r = layoutLabels(nodes, { ...opts, measure: stub });
  if (r.mode === "legend") return;
  for (const row of [0, 1]) {
    const boxes = r.placements.filter(p => p.row === row)
      .map(p => ({ l: p.x - stub(p.text)/2, r: p.x + stub(p.text)/2 }))
      .sort((a, b) => a.l - b.l);
    boxes.forEach((b, i) => i && expect(b.l).toBeGreaterThanOrEqual(boxes[i-1].r + opts.gap - 0.01));
  }
});
```

Scenarios must include: all four dates on one day; publication and deadline 1 day apart on a 90-day span; a shifted deadline adding a fifth node; a 240px container; a 1200px container. Add a fast property test — 500 random node sets, assert non-overlap and that every input id appears exactly once in `placements ∪ items`.

Playwright: screenshot the macro rail at 1440 / 1280 / 900 / 390 on a fixture tender with a shifted deadline, in both themes.

---

## 4. Catalog: no control over sort order or category grouping

Today `/tenders` offers four fixed sorts as a segmented control, with no direction toggle and no way to order or group by the category fields the analyst actually works in (ОКПД2, заказчик, регион). Fix it as a registry, so a new sort field is one object and zero UI changes.

### 4.1 Model

```ts
// src/entities/tender/model/sort.ts
export type SortDir = "asc" | "desc";

export interface SortField {
  id: string;
  label: string;                    // «по сроку подачи»
  group: "relevance" | "money" | "dates" | "categories";
  apiField: string;                 // what the backend expects
  defaultDir: SortDir;              // deadline → asc, price → desc
  dirLabels: Record<SortDir, string>;   // «сначала ближайшие» / «сначала дальние»
  availableWhen?: (q: TenderQuery) => boolean;   // relevance needs a query
  groupable?: boolean;              // may also be used for grouping (§4.3)
}

export const SORT_FIELDS: readonly SortField[] = [
  { id: "relevance", group: "relevance", label: "по релевантности", apiField: "score",
    defaultDir: "desc", dirLabels: { desc: "сначала точные", asc: "сначала неточные" },
    availableWhen: (q) => Boolean(q.query || q.semantic) },
  { id: "deadline", group: "dates", label: "по сроку подачи", apiField: "submission_deadline",
    defaultDir: "asc", dirLabels: { asc: "сначала ближайшие", desc: "сначала дальние" } },
  { id: "published", group: "dates", label: "по дате публикации", apiField: "published_at",
    defaultDir: "desc", dirLabels: { desc: "сначала новые", asc: "сначала старые" } },
  { id: "price", group: "money", label: "по начальной цене", apiField: "start_price",
    defaultDir: "desc", dirLabels: { desc: "сначала дорогие", asc: "сначала дешёвые" } },
  { id: "okpd", group: "categories", label: "по ОКПД2", apiField: "okpd2_code",
    defaultDir: "asc", dirLabels: { asc: "по возрастанию кода", desc: "по убыванию кода" },
    groupable: true },
  { id: "customer", group: "categories", label: "по заказчику", apiField: "customer_name",
    defaultDir: "asc", dirLabels: { asc: "А → Я", desc: "Я → А" }, groupable: true },
  { id: "region", group: "categories", label: "по региону", apiField: "region_name",
    defaultDir: "asc", dirLabels: { asc: "А → Я", desc: "Я → А" }, groupable: true },
];
```

Adding a field later touches this array only. Nothing in the UI enumerates sorts by hand.

Two invariants:

- **Stable tie-break.** Always append `id:asc` to the outgoing sort. Without it, cursor pagination duplicates and skips rows on low-cardinality keys like region — a bug that shows up only on page 3 and is miserable to trace.
- **Sort change resets the cursor** and scrolls the virtualizer to 0. Never merge pages sorted differently.

### 4.2 Control and URL

Replace the segmented control with a `SortControl` button + popover — segmented controls do not survive seven options and a direction.

```
[ Сортировка: по сроку подачи · сначала ближайшие  ▾ ]

  ┌────────────────────────────────┐
  │ Соответствие                    │
  │   ✓ по релевантности            │
  │ Даты                            │
  │     по сроку подачи             │
  │     по дате публикации          │
  │ Цена                            │
  │     по начальной цене           │
  │ Категории                       │
  │     по ОКПД2                    │
  │     по заказчику                │
  │     по региону                  │
  │ ───────────────────────────────│
  │ Порядок  [ сначала ближайшие ▾ ]│
  │ Группировать по  [ нет ▾ ]      │
  └────────────────────────────────┘
```

- Groups are labelled by `SortField.group`, rendered in registry order, headers from one `SORT_GROUP_LABELS` map.
- Selecting a field applies its `defaultDir`; the direction row re-labels itself from `dirLabels` — never a bare «↑ / ↓», which is meaningless on «по заказчику».
- `availableWhen === false` renders the option disabled with «доступно при поисковом запросе», not hidden — hiding options makes the control feel unstable.
- The trigger always states the current state in words; `aria-live="polite"` announces the change.

URL state, multi-key ready from day one:

```
?sort=deadline:asc
?sort=okpd:asc,price:desc          // parser accepts n keys, UI writes 1 today
?group=customer
```

Parser in `entities/tender/model/sort.ts`: unknown ids and directions are dropped with a fallback to the default sort — a stale bookmark must never render an error page.

### 4.3 Grouping (the second reading of "по категориям")

`Группировать по` = нет | ОКПД2 | заказчик | регион, populated from `SORT_FIELDS.filter(f => f.groupable)`.

When active:

- The list gains sticky group headers: category name, item count with correct plural, aggregate НМЦК, and a collapse chevron. Collapsed group ids go in the URL (`&collapsed=okpd:32.50,...`).
- **Virtualization:** flatten to `Array<{kind:"header"; …} | {kind:"row"; …}>` and give the virtualizer a per-index `estimateSize` (40 for headers, 72 for rows). Do not nest virtualizers.
- Sorting within a group uses the selected sort; the group key becomes the primary sort key server-side, so grouping is `sort=<group>:asc,<selected>:<dir>,id:asc` — grouping and sorting are one request, never a client-side regroup of a paginated page.
- Grouping is disabled while `sort=relevance` with an explanatory tooltip: relevance order and category order contradict each other. Say so, do not silently ignore one.

### 4.4 Guards

- Unit: parse/serialize round-trip including unknown ids, empty, multi-key; tie-break always appended; `defaultDir` applied on field switch.
- Unit: flattening a grouped result yields correct index→size mapping and stable keys.
- Playwright: choose «по заказчику», reload the URL, expect the same order and the same trigger label; collapse a group, reload, expect it still collapsed; switch sort mid-scroll, expect the list at position 0 with no duplicate ids.

---

## 5. Order of work

1. §1 tokens + lint rule + contrast test (blocks the rest — do not build UI against the old spelling).
2. §1.4 migration, screen by screen, both themes, `/dev/contrast` verified.
3. §3 label layout in `shared/`, unit tests green, then adopt in `Rail`, then in the other time axes.
4. §4 sort registry → control → URL → grouping.
5. §2 top bar (last, because it is the smallest diff and easiest to eyeball once contrast is right).
6. Full pass: 1920 / 1440 / 1280 / 900 / 390, both themes, keyboard-only run of the five Playwright flows, `pnpm lint && pnpm typecheck && pnpm lint:boundaries && pnpm test`.

## 6. Done when

- [ ] No component outside `shared/ui/` references a palette token; lint enforces it
- [ ] Contrast test green for every pair in both themes; `text-subtle` documented as non-text/AA-large only
- [ ] Every coloured background in the app sets its paired foreground
- [ ] Rail labels never overlap at any of the tested scenarios and container widths; overflow degrades short → two-row → legend, never dropped
- [ ] Rail layout recomputes after webfont load and on resize; `micro` does zero measurement
- [ ] Seven sort fields, each with a direction stated in words; grouping by three category fields; both in the URL and restorable
- [ ] Sort/group changes reset pagination; tie-break by id always present
- [ ] `⌘K` chip inside the search field; palette still opens from every route; nothing else in the top bar grew to fill the space
- [ ] `docs/DESIGN.md` documents the pair-token rule and the label escalation ladder; `docs/CHANGELOG.md` lists the four fixes
