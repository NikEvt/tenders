"use client";

import { ru } from "@/shared/i18n/ru";

/**
 * Последний рубеж: сюда попадают падения в корневом лейауте, где ни темы, ни
 * провайдеров ещё нет. Поэтому стили здесь встроенные, без токенов.
 */
export default function GlobalError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="ru">
      <body
        style={{
          margin: 0,
          minHeight: "100dvh",
          display: "grid",
          placeItems: "center",
          background: "#f2f3f0",
          color: "#12151a",
          fontFamily: "system-ui, sans-serif",
          padding: 24,
        }}
      >
        <div style={{ maxWidth: 560 }}>
          <h1 style={{ fontSize: 26, margin: "0 0 12px" }}>{ru.errors.title}</h1>
          <p style={{ margin: "0 0 8px", lineHeight: 1.5 }}>{error.message}</p>
          <p style={{ margin: "0 0 20px", color: "#5a615a", lineHeight: 1.5 }}>
            {ru.errors.network}
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              height: 40,
              padding: "0 16px",
              borderRadius: 6,
              border: 0,
              background: "#0d4cd3",
              color: "#fff",
              fontSize: 15,
              cursor: "pointer",
            }}
          >
            {ru.common.retry}
          </button>
        </div>
      </body>
    </html>
  );
}
