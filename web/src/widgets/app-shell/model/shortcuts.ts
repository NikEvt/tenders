import { ru } from "@/shared/i18n/ru";

/** Единый источник таблицы горячих клавиш: лист по «?» и страница /help. */
export const SHORTCUTS: { keys: string; action: string }[] = [
  { keys: "⌘K / Ctrl+K", action: ru.keyboard.palette },
  { keys: "/", action: ru.keyboard.focusSearch },
  { keys: "j", action: ru.keyboard.nextRow },
  { keys: "k", action: ru.keyboard.prevRow },
  { keys: "Enter", action: ru.keyboard.openRow },
  { keys: "Shift+Enter", action: ru.keyboard.openNewTab },
  { keys: "f", action: ru.keyboard.favourite },
  { keys: "h", action: ru.keyboard.hideRow },
  { keys: "s", action: ru.keyboard.similarRow },
  { keys: "1…5", action: ru.keyboard.switchTabs },
  { keys: "g d / g c / g f / g r / g m", action: ru.keyboard.goto },
  { keys: "Esc", action: ru.keyboard.escape },
  { keys: "?", action: ru.keyboard.sheet },
];
