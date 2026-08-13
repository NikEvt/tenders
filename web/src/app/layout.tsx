import type { Metadata, Viewport } from "next";
import { ru } from "@/shared/i18n/ru";
import { AppShell } from "@/widgets/app-shell/ui/app-shell";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: ru.app.name, template: `%s · ${ru.app.name}` },
  description:
    "Рабочее место аналитика по закупкам 44-ФЗ: каталог, ИИ-фильтрация с ссылками на источник, сводка дня и рекомендации.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f2f3f0" },
    { media: "(prefers-color-scheme: dark)", color: "#14161a" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <head>
        {/* Два самых частых начертания грузим заранее: остальное подтянется по мере надобности. */}
        <link
          rel="preload"
          href="/fonts/golos-text-400.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
        <link
          rel="preload"
          href="/fonts/golos-text-600.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
      </head>
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
