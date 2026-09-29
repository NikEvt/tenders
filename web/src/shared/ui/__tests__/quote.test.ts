import { describe, expect, test } from "vitest";
import { trimAroundMatch } from "@/shared/ui/quote";

/**
 * Сторож одного правила: совпадение остаётся видимым при любой длине цитаты.
 *
 * Правило появилось не из вкуса. При разборе прогона ХПК/БПК цитата обрезалась
 * по первым 155 символам, то есть показывался один левый контекст, а искомое
 * слово оставалось за кадром — и по таким превью были сделаны неверные выводы.
 */
const long = (fill: string, n: number) => fill.repeat(n);

describe("обрезка цитаты", () => {
  test("совпадение видно, даже когда стоит в конце длинной цитаты", () => {
    const quote = `${long("а", 500)}БПК5`;
    const { match, cutStart } = trimAroundMatch(
      { quote, match_start: 500, match_end: 504 },
      90,
    );

    expect(match).toBe("БПК5");
    expect(cutStart).toBe(true);
  });

  test("совпадение видно, когда стоит в начале", () => {
    const quote = `БПК5${long("б", 500)}`;
    const { match, cutEnd } = trimAroundMatch({ quote, match_start: 0, match_end: 4 }, 90);

    expect(match).toBe("БПК5");
    expect(cutEnd).toBe(true);
  });

  test("контекст берётся с обеих сторон", () => {
    const quote = `${long("а", 200)}БПК5${long("б", 200)}`;
    const { before, after } = trimAroundMatch(
      { quote, match_start: 200, match_end: 204 },
      50,
    );

    expect(before).toHaveLength(50);
    expect(after).toHaveLength(50);
  });

  test("короткая цитата не режется вовсе", () => {
    const { cutStart, cutEnd, before, after } = trimAroundMatch(
      { quote: "норматив по БПК5 в стоках", match_start: 12, match_end: 16 },
      90,
    );

    expect(cutStart).toBe(false);
    expect(cutEnd).toBe(false);
    expect(before).toBe("норматив по ");
    expect(after).toBe(" в стоках");
  });

  test("битые границы не роняют показ", () => {
    // Старая запись или обрезанный текст: смещение за пределами строки.
    const { match } = trimAroundMatch(
      { quote: "короткая", match_start: 500, match_end: 900 },
      90,
    );

    expect(match).toBe("");
  });

  test("перевёрнутые границы не дают отрицательного среза", () => {
    const { match, before } = trimAroundMatch(
      { quote: "норматив БПК5", match_start: 9, match_end: 4 },
      90,
    );

    expect(match).toBe("");
    expect(before).toBe("норматив ");
  });
});
