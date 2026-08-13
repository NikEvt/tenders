import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";
import {
  CONTRAST_PAIRS,
  contrastRatio,
  readTokenSheet,
  resolveToken,
  type Theme,
} from "@/shared/lib/tokens";

/**
 * Контраст проверяется по самому `globals.css`, а не по копии списка значений:
 * тест обязан падать, когда кто-то правит CSS, а не когда кто-то вспомнил
 * обновить дубликат. Сам список пар тоже один на всё приложение — он лежит
 * рядом с разбором, в `shared/lib/tokens.ts`, и его же читает /dev/contrast.
 */
const sheet = readTokenSheet(readFileSync("src/app/globals.css", "utf8"));

describe.each(["light", "dark"] as const)("контраст · %s", (theme: Theme) => {
  test.each(CONTRAST_PAIRS.map((p) => [p.fg, p.bg, p.min] as const))(
    "%s на %s",
    (fg, bg, min) => {
      const foreground = resolveToken(sheet, theme, fg);
      const background = resolveToken(sheet, theme, bg);
      const ratio = contrastRatio(foreground, background);

      expect(
        ratio,
        `${fg} (${foreground}) на ${bg} (${background}) — ${ratio.toFixed(2)}:1, нужно ${min}:1`,
      ).toBeGreaterThanOrEqual(min);
    },
  );
});

describe("контракт токенов", () => {
  /** Фон — это `*-bg`, `*-tint` и веллум; `--color-on-*` сам фоном не бывает. */
  const backgrounds = Object.keys(sheet.light).filter(
    (name) =>
      !name.startsWith("--color-on-") &&
      (/^--color-.*-(bg|tint)$/.test(name) ||
        name === "--color-vellum" ||
        name === "--color-row-active"),
  );

  const partnerOf = (background: string) =>
    `--color-on-${background.replace(/^--color-/, "").replace(/-bg$/, "")}`;

  test("список фонов не пуст — иначе следующие два теста ничего не проверяют", () => {
    expect(backgrounds.length).toBeGreaterThanOrEqual(6);
  });

  test("у каждого фонового токена есть парный --color-on-*", () => {
    const missing = backgrounds.filter((name) => !(partnerOf(name) in sheet.light));
    expect(missing, `фон без пары: ${missing.join(", ")}`).toEqual([]);
  });

  test("пара переезжает в тёмную тему целиком", () => {
    // Переехал фон — обязан переехать и его текст. Исключение ровно одно:
    // текст, который в обеих темах белый, — он и есть «переехал без изменений».
    for (const background of backgrounds) {
      const partner = partnerOf(background);
      const moved = (name: string) =>
        resolveToken(sheet, "light", name) !== resolveToken(sheet, "dark", name);

      if (!moved(background)) continue;
      expect(
        moved(partner) || resolveToken(sheet, "dark", partner) === "#ffffff",
        `${background} меняется в тёмной теме, а ${partner} — нет`,
      ).toBe(true);
    }
  });

  test("палитра не переопределяется темой", () => {
    const palette = Object.keys(sheet.light).filter((name) => name.startsWith("--palette-"));
    expect(palette.length).toBeGreaterThan(0);

    const overridden = palette.filter((name) => sheet.light[name] !== sheet.dark[name]);
    expect(overridden, `палитра сдвинулась в тёмной теме: ${overridden.join(", ")}`).toEqual([]);
  });

  test("фоновый токен ссылается в палитру, а не в другой фоновый токен", () => {
    // `--color-canvas: var(--color-surface)` завязал бы две роли в одну и
    // тихо сломался бы при первой же правке одной из них.
    const leaks = backgrounds.filter((name) => /var\(\s*--color-/.test(sheet.light[name]!));
    expect(leaks).toEqual([]);
  });
});
