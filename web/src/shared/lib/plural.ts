const rules = new Intl.PluralRules("ru-RU");

/**
 * Русские формы числительных: `plural(n, ["закупка", "закупки", "закупок"])`.
 * Отдельный помощник, потому что `n + " закупок"` неверно в 20% случаев,
 * а это самый частый текст в интерфейсе.
 */
export function plural(n: number, forms: [string, string, string]): string {
  switch (rules.select(n)) {
    case "one":
      return forms[0];
    case "few":
      return forms[1];
    default:
      return forms[2];
  }
}

export function withPlural(n: number, forms: [string, string, string]): string {
  return `${formatCount(n)}\u00a0${plural(n, forms)}`;
}

const countFormat = new Intl.NumberFormat("ru-RU");

/** Счётчики группируются по три: 1 248. */
export function formatCount(n: number): string {
  return countFormat.format(n);
}
