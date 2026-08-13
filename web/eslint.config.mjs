import js from "@eslint/js";
import tseslint from "typescript-eslint";
import { FlatCompat } from "@eslint/eslintrc";
import { layers } from "./eslint.boundaries.mjs";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

/**
 * Слои клиента повторяют дисциплину бэкенда (`lint-imports`):
 * app → widgets → features → entities → shared, и никогда наоборот.
 * Само правило описано в eslint.boundaries.mjs — оно же запускается отдельно
 * командой `pnpm lint:boundaries`.
 */
export default tseslint.config(
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts", "src/shared/api/schema.d.ts"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...compat.extends("next/core-web-vitals"),
  layers,
  {
    // Правила, которым нужна информация о типах, применяются только к
    // исходникам: конфиги лежат вне tsconfig.
    files: ["src/**/*.ts", "src/**/*.tsx"],
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/consistent-type-imports": [
        "error",
        { prefer: "type-imports", fixStyle: "inline-type-imports" },
      ],
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    /**
     * Сырой ряд недоступен нигде, кроме самого `globals.css`.
     *
     * Переименование `--color-n-*` → `--palette-*` уже убрало утилиты
     * `bg-n-25` из Tailwind, поэтому старое написание падает на сборке. Это
     * правило закрывает обратную дорогу: и возврат прежних имён, и попытку
     * дотянуться до палитры через `var(--palette-…)` из компонента.
     */
    files: ["src/**/*.ts", "src/**/*.tsx"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "Literal[value=/\\b(bg|text|border|border-[trbl]|fill|stroke|ring|outline|accent|decoration|divide|from|via|to|caret|placeholder|shadow)-n-\\d+\\b/]",
          message:
            "Сырой ряд здесь недоступен. Возьмите семантический токен (surface, canvas, hairline, text-muted) или парный класс .surface-*.",
        },
        {
          selector: "TemplateElement[value.raw=/\\b(bg|text|border|fill|stroke|ring)-n-\\d+\\b/]",
          message:
            "Сырой ряд здесь недоступен. Возьмите семантический токен или парный класс .surface-*.",
        },
        {
          selector: "Literal[value=/--(palette|color)-n-\\d+/]",
          message:
            "Палитра объявлена только в globals.css. Компонент берёт семантический токен: var(--color-…).",
        },
        {
          selector: "TemplateElement[value.raw=/--(palette|color)-n-\\d+/]",
          message:
            "Палитра объявлена только в globals.css. Компонент берёт семантический токен: var(--color-…).",
        },
        {
          selector: "Literal[value=/--palette-(blue|oak|moss|signal)-/]",
          message:
            "Палитра объявлена только в globals.css. Возьмите пару (--color-*-bg / --color-on-*) или --color-*-fg.",
        },
        {
          /**
           * Второе правило §1.2: цвет как фон и тот же цвет как текст — разные
           * токены. Голого `gos`/`oak`/`moss`/`signal` больше нет ни как
           * утилиты, ни как переменной; есть `-fg` (текст и рисунок) и пара
           * `-bg` + `on-`.
           */
          selector:
            "Literal[value=/\\b(bg|text|border|border-[trbl]|fill|stroke|ring|accent|outline|decoration|from|via|to)-(gos|oak|moss|signal)(-press)?(?![-\\w])/]",
          message:
            "Такого токена больше нет. Цвет как текст или рисунок — `-fg` (text-gos-fg, bg-oak-fg); цвет как подложка — парный класс .surface-gos / .surface-signal.",
        },
        {
          /**
           * Первое правило §1.2: фон нельзя взять без его текста. Единственный
           * способ поставить цветную подложку — парный класс, который ставит
           * обе стороны одним объявлением.
           */
          selector: "Literal[value=/\\bbg-((gos|oak|moss|signal)-tint|vellum|(gos|signal)-bg)\\b/]",
          message:
            "Цветной фон без парного текста. Возьмите .surface-gos-tint / .surface-oak-tint / .surface-moss-tint / .surface-signal-tint / .surface-vellum / .surface-gos / .surface-signal.",
        },
      ],
    },
  },
  {
    // Тест контраста и страница /dev/contrast читают токены по именам — это
    // их работа, а не обращение к палитре из компонента.
    files: ["src/shared/lib/tokens.ts", "src/shared/ui/__tests__/contrast.test.ts"],
    rules: { "no-restricted-syntax": "off" },
  },
  {
    files: ["**/*.test.ts", "**/*.test.tsx", "vitest.config.ts", "vitest.setup.ts"],
    rules: { "boundaries/element-types": "off" },
  },
);
