import * as React from "react";
import { cn } from "@/shared/lib/cn";

/**
 * Минимальный разбор Markdown для текста, который написала модель:
 * заголовки, абзацы, списки, **жирный**, `код`.
 *
 * Своё, а не библиотека, по двум причинам: нужен ровно этот набор, и результат
 * собирается React-узлами. Текст от модели никогда не попадает в HTML — ни
 * здесь, ни в просмотрщике документов (§8.4).
 */
export function Markdown({ source, className }: { source: string; className?: string }) {
  const blocks = React.useMemo(() => parseBlocks(source), [source]);

  return (
    <div className={cn("measure flex flex-col gap-3 leading-[1.6]", className)}>
      {blocks.map((block, index) => {
        if (block.type === "heading") {
          const Tag = block.level === 1 ? "h2" : "h3";
          return (
            <Tag key={index} className={block.level === 1 ? "text-h2" : "text-h3"}>
              {inline(block.text)}
            </Tag>
          );
        }
        if (block.type === "list") {
          return (
            <ul key={index} className="flex list-disc flex-col gap-1.5 pl-5">
              {block.items.map((item, i) => (
                <li key={i}>{inline(item)}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={index} className="text-body">
            {inline(block.text)}
          </p>
        );
      })}
    </div>
  );
}

type Block =
  | { type: "heading"; level: 1 | 2; text: string }
  | { type: "paragraph"; text: string }
  | { type: "list"; items: string[] };

function parseBlocks(source: string): Block[] {
  const blocks: Block[] = [];
  let list: string[] = [];

  const flush = () => {
    if (list.length) {
      blocks.push({ type: "list", items: list });
      list = [];
    }
  };

  for (const rawLine of source.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      flush();
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flush();
      blocks.push({
        type: "heading",
        level: heading[1]!.length <= 2 ? 1 : 2,
        text: heading[2]!,
      });
      continue;
    }
    const item = /^[-*•]\s+(.*)$/.exec(line);
    if (item) {
      list.push(item[1]!);
      continue;
    }
    flush();
    const previous = blocks[blocks.length - 1];
    if (previous?.type === "paragraph") previous.text += ` ${line}`;
    else blocks.push({ type: "paragraph", text: line });
  }

  flush();
  return blocks;
}

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`)/g;

function inline(text: string): React.ReactNode[] {
  return text.split(INLINE).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={index} className="font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={index} className="font-mono text-mono">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
}
