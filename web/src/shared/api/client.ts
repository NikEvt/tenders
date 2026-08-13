import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

const TIMEOUT_MS = 30_000;

/**
 * Токена сегодня нет: режим однопользовательский, экрана входа не будет (§9.10).
 * Перехватчик всё равно стоит — при появлении многопользовательского режима
 * меняется только эта функция и появляется маршрут входа.
 */
export function getToken(): string | null {
  return null;
}

const auth: Middleware = {
  async onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
};

/**
 * Ключ идемпотентности на всех POST, которые ставят задачу или пишут оценку:
 * повтор из-за таймаута не должен удваивать сигнал в профиле.
 */
const idempotency: Middleware = {
  async onRequest({ request }) {
    if (request.method === "POST" && !request.headers.has("Idempotency-Key")) {
      request.headers.set("Idempotency-Key", crypto.randomUUID());
    }
    return request;
  },
};

export const api = createClient<paths>({
  baseUrl: API_URL,
  headers: { "Content-Type": "application/json" },
});

api.use(auth, idempotency);

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly endpoint: string,
    readonly detail: string,
    readonly requestId: string | null = null,
  ) {
    super(detail);
    this.name = "ApiError";
  }

  /** Для кнопки «Скопировать детали» в error.tsx. */
  toClipboard(): string {
    return [
      `endpoint: ${this.endpoint}`,
      `status: ${this.status}`,
      `detail: ${this.detail}`,
      this.requestId ? `request-id: ${this.requestId}` : null,
      `time: ${new Date().toISOString()}`,
    ]
      .filter(Boolean)
      .join("\n");
  }
}

type FastApiError = { detail?: unknown };

function readDetail(body: unknown): string {
  const detail = (body as FastApiError | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const record = item as { loc?: unknown[]; msg?: string };
        const loc = Array.isArray(record.loc) ? record.loc.join(".") : "";
        return [loc, record.msg].filter(Boolean).join(": ");
      })
      .join("; ");
  }
  return "";
}

/**
 * Обёртка над openapi-fetch: разворачивает `{data, error, response}` в значение
 * или бросает `ApiError` — Query умеет работать только с исключениями.
 *
 * `data` приходит как `unknown`: часть эндпоинтов FastAPI объявляет возврат
 * просто `dict`, и в схеме они выглядят как `{[key: string]: unknown}`. Тип
 * результата задаётся параметром `T` на месте вызова, а формы этих ответов
 * описаны в `types.ts` — там же указано, каким исходникам они соответствуют.
 */
export async function unwrap<T>(
  endpoint: string,
  call: (init: { signal?: AbortSignal }) => Promise<{
    data?: unknown;
    error?: unknown;
    response: Response;
  }>,
  signal?: AbortSignal,
): Promise<T> {
  const timeout = AbortSignal.timeout(TIMEOUT_MS);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;

  let result: { data?: unknown; error?: unknown; response: Response };
  try {
    result = await call({ signal: combined });
  } catch (cause) {
    if (combined.aborted && !signal?.aborted) {
      throw new ApiError(408, endpoint, `Запрос к ${endpoint} шёл дольше 30 секунд.`);
    }
    throw new ApiError(0, endpoint, describeNetworkError(cause));
  }

  const { data, error, response } = result;
  if (error !== undefined || !response.ok) {
    throw new ApiError(
      response.status,
      endpoint,
      readDetail(error) || `${response.status} ${response.statusText}`,
      response.headers.get("X-Request-Id"),
    );
  }
  return data as T;
}

function describeNetworkError(cause: unknown): string {
  const message = cause instanceof Error ? cause.message : String(cause);
  return `Нет связи с API (${API_URL}): ${message}`;
}
