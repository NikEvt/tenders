import boundaries from "eslint-plugin-boundaries";
import tseslint from "typescript-eslint";

/**
 * Только проверка слоёв — прямой аналог `lint-imports` в Python-части.
 * Вынесена в отдельный конфиг, чтобы её можно было запускать отдельным шагом
 * CI и читать вывод, не разбирая его среди прочих замечаний линтера.
 *
 * Тот же объект подключается и в основном eslint.config.mjs.
 */
export const layers = {
  files: ["src/**/*.ts", "src/**/*.tsx"],
  languageOptions: { parser: tseslint.parser },
  plugins: { boundaries },
  settings: {
    "boundaries/include": ["src/**/*"],
    "boundaries/elements": [
      { type: "app", pattern: "src/app/**/*" },
      { type: "widgets", pattern: "src/widgets/*", mode: "folder", capture: ["slice"] },
      { type: "features", pattern: "src/features/*", mode: "folder", capture: ["slice"] },
      { type: "entities", pattern: "src/entities/*", mode: "folder", capture: ["slice"] },
      { type: "shared", pattern: "src/shared/**/*" },
    ],
  },
  rules: {
    "boundaries/no-unknown": "off",
    "boundaries/no-unknown-files": "off",
    "boundaries/element-types": [
      "error",
      {
        default: "disallow",
        rules: [
          { from: "app", allow: ["widgets", "features", "entities", "shared"] },
          { from: "widgets", allow: ["features", "entities", "shared"] },
          { from: "features", allow: ["entities", "shared"] },
          // Внутри слайса — свободно, между слайсами одного слоя — нельзя.
          { from: "entities", allow: [["entities", { slice: "${from.slice}" }], "shared"] },
          { from: "shared", allow: ["shared"] },
        ],
      },
    ],
  },
};

// Конфиг намеренно узкий: правил, кроме слоёв, здесь нет, поэтому отключения
// в коде выглядели бы неиспользованными.
const config = [
  { ignores: [".next/**", "node_modules/**"] },
  { linterOptions: { reportUnusedDisableDirectives: "off" } },
  layers,
];

export default config;
