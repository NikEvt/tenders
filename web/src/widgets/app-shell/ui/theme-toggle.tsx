"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import { Monitor, Moon, Sun } from "lucide-react";
import { Segmented, type SegmentedOption } from "@/shared/ui/segmented";
import { ru } from "@/shared/i18n/ru";

type ThemeValue = "light" | "dark" | "system";

const OPTIONS: SegmentedOption<ThemeValue>[] = [
  {
    value: "light",
    label: <Sun className="h-4 w-4" strokeWidth={1.5} />,
    title: ru.nav.themeLight,
    ariaLabel: ru.nav.themeLight,
  },
  {
    value: "dark",
    label: <Moon className="h-4 w-4" strokeWidth={1.5} />,
    title: ru.nav.themeDark,
    ariaLabel: ru.nav.themeDark,
  },
  {
    value: "system",
    label: <Monitor className="h-4 w-4" strokeWidth={1.5} />,
    title: ru.nav.themeSystem,
    ariaLabel: ru.nav.themeSystem,
  },
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  // До гидратации выбранная тема неизвестна. Рисовать «светлую» активной нельзя —
  // это мигание переключателя при каждой загрузке.
  React.useEffect(() => setMounted(true), []);
  if (!mounted) return <div className="h-9 w-[104px]" aria-hidden="true" />;

  return (
    <Segmented
      size="sm"
      label={ru.nav.theme}
      value={(theme as ThemeValue) ?? "system"}
      onChange={setTheme}
      options={OPTIONS}
    />
  );
}
