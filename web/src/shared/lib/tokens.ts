/**
 * Чтение токенов прямо из `globals.css`.
 *
 * Единственный источник правды о цвете — сам файл стилей. Тест контраста и
 * страница `/dev/contrast` разбирают его, а не сверяются с копией списка:
 * копия расходится с оригиналом ровно в тот день, когда о ней забывают.
 *
 * Разбор намеренно наивный — ему нужно понимать три вещи, которые мы сами и
 * пишем: объявления `--имя: значение`, ссылки `var(--другое-имя)` и три блока,
 * в которых они лежат.
 */

export type Theme = "light" | "dark";

export type TokenSheet = Record<Theme, Record<string, string>>;

/** Блоки, из которых собирается светлая тема, и блок, который её переопределяет. */
const LIGHT_SELECTORS = [":root", "@theme inline", "@theme"];
const DARK_SELECTOR = '[data-theme="dark"]';

/**
 * Вырезает тело блока по его заголовку, считая скобки: внутри `@layer` есть
 * вложенные правила, и регулярка «до первой `}`» на них ломается.
 */
function blockBodies(css: string, selector: string): string[] {
  const bodies: string[] = [];
  let from = 0;

  for (;;) {
    const head = css.indexOf(selector, from);
    if (head === -1) break;

    const open = css.indexOf("{", head + selector.length);
    // Между заголовком и `{` не должно быть ничего, кроме пробелов: иначе это
    // совпадение внутри другого селектора (`@theme` внутри `@theme inline`).
    if (open === -1 || css.slice(head + selector.length, open).trim() !== "") {
      from = head + selector.length;
      continue;
    }

    let depth = 0;
    let index = open;
    for (; index < css.length; index += 1) {
      if (css[index] === "{") depth += 1;
      else if (css[index] === "}") {
        depth -= 1;
        if (depth === 0) break;
      }
    }

    bodies.push(css.slice(open + 1, index));
    from = index + 1;
  }

  return bodies;
}

const DECLARATION = /(--[\w-]+)\s*:\s*([^;}]+)/g;

/** Объявления верхнего уровня блока — вложенные правила пропускаются. */
function declarations(body: string): Record<string, string> {
  const flat = body.replace(/\{[^{}]*\}/g, "");
  const found: Record<string, string> = {};
  for (const match of flat.matchAll(DECLARATION)) {
    found[match[1]!] = match[2]!.trim();
  }
  return found;
}

export function readTokenSheet(css: string): TokenSheet {
  const light: Record<string, string> = {};
  for (const selector of LIGHT_SELECTORS) {
    for (const body of blockBodies(css, selector)) Object.assign(light, declarations(body));
  }

  const dark = { ...light };
  for (const body of blockBodies(css, DARK_SELECTOR)) Object.assign(dark, declarations(body));

  return { light, dark };
}

const VAR_REFERENCE = /^var\(\s*(--[\w-]+)\s*\)$/;

/**
 * Значение токена в конкретной теме, с раскрытием цепочки `var(...)`.
 *
 * Именно здесь ловится ошибка «семантический токен указывает в палитру, а
 * палитра в тёмной теме не меняется»: цепочка раскрывается в карте своей темы.
 */
export function resolveToken(sheet: TokenSheet, theme: Theme, name: string): string {
  const scope = sheet[theme];
  let value: string | undefined = scope[name];
  const seen = new Set<string>([name]);

  while (value !== undefined) {
    const reference = VAR_REFERENCE.exec(value.trim());
    if (!reference) return value.trim();

    const next = reference[1]!;
    if (seen.has(next)) throw new Error(`Циклическая ссылка токена: ${name}`);
    seen.add(next);
    value = scope[next];
  }

  throw new Error(`Токен не объявлен: ${name} (${theme})`);
}

/* ------------------------------------------------------------- список пар */

/** Обычный текст — 4.5:1. */
export const AA = 4.5;
/** Нетекстовые роли: значки, разделители, placeholder, выключенные состояния. */
export const AA_LARGE = 3;

export type ContrastPair = { fg: string; bg: string; min: number; note?: string };

const pair = (fg: string, bg: string, min = AA, note?: string): ContrastPair => ({
  fg,
  bg,
  min,
  note,
});

/**
 * Каждая пара «текст на фоне», которую обязан выдержать интерфейс.
 *
 * Один список на две задачи: тест `contrast.test.ts` считает по нему цифры из
 * `globals.css`, страница `/dev/contrast` — из `getComputedStyle`. Разойтись
 * им негде, потому что списка ровно один.
 */
export const CONTRAST_PAIRS: readonly ContrastPair[] = [
  pair("--color-text", "--color-canvas"),
  pair("--color-text", "--color-surface"),
  pair("--color-text", "--color-surface-raised"),
  pair("--color-text", "--color-surface-sunken"),
  pair("--color-text-muted", "--color-canvas"),
  pair("--color-text-muted", "--color-surface"),
  pair("--color-text-muted", "--color-surface-sunken"),
  pair("--color-text-subtle", "--color-surface", AA_LARGE, "нетекстовая роль"),
  pair("--color-text-subtle", "--color-canvas", AA_LARGE, "нетекстовая роль"),

  pair("--color-on-gos", "--color-gos-bg"),
  pair("--color-on-gos", "--color-gos-bg-press"),
  pair("--color-on-signal", "--color-signal-bg"),

  pair("--color-on-gos-tint", "--color-gos-tint"),
  pair("--color-on-oak-tint", "--color-oak-tint"),
  pair("--color-on-moss-tint", "--color-moss-tint"),
  pair("--color-on-signal-tint", "--color-signal-tint"),
  pair("--color-on-vellum", "--color-vellum"),
  pair("--color-on-row-active", "--color-row-active"),
  pair("--color-text-muted", "--color-row-active"),

  pair("--color-gos-fg", "--color-canvas"),
  pair("--color-gos-fg", "--color-surface"),
  pair("--color-oak-fg", "--color-canvas"),
  pair("--color-oak-fg", "--color-surface"),
  pair("--color-oak-fg", "--color-vellum"),
  pair("--color-moss-fg", "--color-canvas"),
  pair("--color-moss-fg", "--color-surface"),
  pair("--color-signal-fg", "--color-canvas"),
  pair("--color-signal-fg", "--color-surface"),
];

/* ---------------------------------------------------------------- контраст */

export type Rgb = { r: number; g: number; b: number };

export function parseColor(value: string): Rgb {
  const hex = value.trim().replace(/^#/, "");
  const full =
    hex.length === 3
      ? hex
          .split("")
          .map((c) => c + c)
          .join("")
      : hex;

  if (!/^[0-9a-f]{6}$/i.test(full)) throw new Error(`Не цвет: ${value}`);

  return {
    r: parseInt(full.slice(0, 2), 16),
    g: parseInt(full.slice(2, 4), 16),
    b: parseInt(full.slice(4, 6), 16),
  };
}

/** Относительная яркость по WCAG 2.1. */
export function luminance(color: Rgb): number {
  const channel = (value: number) => {
    const srgb = value / 255;
    return srgb <= 0.03928 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
}

export function contrastRatio(foreground: string, background: string): number {
  const a = luminance(parseColor(foreground));
  const b = luminance(parseColor(background));
  const [light, dark] = a > b ? [a, b] : [b, a];
  return (light! + 0.05) / (dark! + 0.05);
}
