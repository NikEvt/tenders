/**
 * Извлечённый текст бывает мусором после OCR: управляющие символы, простыни
 * пробелов, разорванные строки. Чистим, но не переписываем — абзацы важны для
 * чтения, а «улучшать» текст документа мы права не имеем.
 */
export function sanitizeText(raw: string): string {
  return (
    raw
      .replace(/\r\n?/g, "\n")
      // Управляющие символы, кроме перевода строки и табуляции. Регулярка по
      // control-символам здесь и есть смысл функции — правило снято намеренно.
      // eslint-disable-next-line no-control-regex
      .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "")
      // Мягкий перенос: после OCR он рвёт слова прямо посреди строки.
      .replace(/\u00AD/g, "")
      .replace(/[ \t]+/g, " ")
      .replace(/\n{3,}/g, "\n\n")
      .trim()
  );
}

export const CHUNK_CHARS = 2000;

/** Режем на куски по абзацам — так виртуализация не рвёт предложения. */
export function splitForRender(text: string, size = CHUNK_CHARS): string[] {
  const parts: string[] = [];
  let current = "";

  for (const paragraph of text.split("\n\n")) {
    if (current.length + paragraph.length > size && current) {
      parts.push(current);
      current = "";
    }
    current += (current ? "\n\n" : "") + paragraph;
  }
  if (current) parts.push(current);

  return parts;
}

export type Match = { start: number; end: number };

/** Поиск по документу без регулярок: запрос вводит человек, не автор паттернов. */
export function findMatches(text: string, needle: string): Match[] {
  if (needle.trim().length < 2) return [];

  const haystack = text.toLowerCase();
  const query = needle.toLowerCase();
  const matches: Match[] = [];
  let from = 0;

  for (;;) {
    const index = haystack.indexOf(query, from);
    if (index === -1) break;
    matches.push({ start: index, end: index + query.length });
    from = index + query.length;
  }

  return matches;
}

/**
 * Подсветка собирается React-узлами из смещений. `dangerouslySetInnerHTML`
 * с текстом документа не используется нигде и никогда (§8.4).
 */
export function segments(text: string, matches: Match[]): { text: string; match: boolean }[] {
  if (matches.length === 0) return [{ text, match: false }];

  const result: { text: string; match: boolean }[] = [];
  let cursor = 0;

  for (const match of matches) {
    if (match.start > cursor) result.push({ text: text.slice(cursor, match.start), match: false });
    result.push({ text: text.slice(match.start, match.end), match: true });
    cursor = match.end;
  }
  if (cursor < text.length) result.push({ text: text.slice(cursor), match: false });

  return result;
}
