/**
 * Minimal, typed fetch wrapper for the ORBIT REST API.
 *
 * - Same-origin calls to `/api/v1/...` (Next.js rewrites proxy them to FastAPI), `credentials: "include"`.
 * - JSON and multipart bodies, query-string serialization.
 * - Errors are normalized to `ApiError` (`status`, `code`, `detail`, optional `fieldErrors`).
 * - 401 → redirect to `/login?next=<current path>` (opt-out with `redirectOnUnauthorized: false`).
 * - CSRF (double submit, docs/PRODUCTION.md §0): every unsafe method carries `X-CSRF-Token`, read from the
 *   `orbit_csrf` cookie or fetched once from `GET /auth/csrf`; a 403 `csrf_failed` refreshes the token and
 *   retries the request once.
 * - 429 → `ApiError.retryAfter` (seconds, from `Retry-After` or the body) and a French message with the delay.
 */
import type { ApiErrorBody } from "./types";

export const API_BASE = "/api/v1";

export type QueryValue = string | number | boolean | null | undefined | ReadonlyArray<string | number>;
export type QueryParams = Record<string, QueryValue>;

export type HttpMethod = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

/** Methods that change state and therefore require the CSRF header. */
const UNSAFE_METHODS: ReadonlySet<HttpMethod> = new Set<HttpMethod>(["POST", "PATCH", "PUT", "DELETE"]);

export const CSRF_HEADER = "X-CSRF-Token";
export const CSRF_COOKIE = "orbit_csrf";
/** Error code returned by the API when the CSRF token is missing or stale. */
export const CSRF_FAILED_CODE = "csrf_failed";

export interface RequestOptions {
  method?: HttpMethod;
  query?: QueryParams;
  /** JSON body (serialized with JSON.stringify). */
  json?: unknown;
  /** Multipart body. Takes precedence over `json`. */
  formData?: FormData;
  signal?: AbortSignal;
  headers?: HeadersInit;
  /** Redirect the browser to /login on 401 (default: true). */
  redirectOnUnauthorized?: boolean;
  /** How to read a successful response body (default: "json"; 204 always yields undefined). */
  responseType?: "json" | "text" | "blob";
}

/** Normalized API error. `status` is 0 for network failures. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly fieldErrors: Record<string, string>;
  readonly body: unknown;
  /** Seconds to wait before retrying (429 / lockout), when the API tells us. */
  readonly retryAfter: number | null;

  constructor(init: {
    status: number;
    code: string;
    detail: string;
    fieldErrors?: Record<string, string>;
    body?: unknown;
    retryAfter?: number | null;
  }) {
    super(init.detail);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.detail = init.detail;
    this.fieldErrors = init.fieldErrors ?? {};
    this.body = init.body;
    this.retryAfter = init.retryAfter ?? null;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
  get isForbidden(): boolean {
    return this.status === 403;
  }
  get isNotFound(): boolean {
    return this.status === 404;
  }
  get isConflict(): boolean {
    return this.status === 409;
  }
  get isValidation(): boolean {
    return this.status === 422 || this.status === 400;
  }
  get isNetwork(): boolean {
    return this.status === 0;
  }
  get isServer(): boolean {
    return this.status >= 500;
  }
  get isRateLimited(): boolean {
    return this.status === 429;
  }
  get isCsrfFailure(): boolean {
    return this.status === 403 && this.code === CSRF_FAILED_CODE;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** User-facing French message for any error. */
export function errorMessage(error: unknown, fallback = "Une erreur inattendue est survenue."): string {
  if (isApiError(error)) return error.detail || fallback;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

const DEFAULT_MESSAGES: Record<number, { code: string; detail: string }> = {
  400: { code: "validation_error", detail: "Requête invalide." },
  401: { code: "unauthorized", detail: "Votre session a expiré. Veuillez vous reconnecter." },
  403: { code: "forbidden", detail: "Vous n'avez pas les droits nécessaires pour cette action." },
  404: { code: "not_found", detail: "Ressource introuvable." },
  409: { code: "conflict", detail: "Conflit avec l'état actuel de la ressource." },
  413: { code: "payload_too_large", detail: "Le fichier envoyé est trop volumineux." },
  422: { code: "validation_error", detail: "Les données envoyées sont invalides." },
  429: { code: "rate_limited", detail: "Trop de requêtes. Réessayez dans un instant." },
};

/** "30 secondes", "2 minutes", "1 h 05" — French human delay for retry messages. */
export function formatRetryDelay(seconds: number): string {
  const s = Math.max(1, Math.ceil(seconds));
  if (s < 60) return `${s} seconde${s > 1 ? "s" : ""}`;
  const minutes = Math.ceil(s / 60);
  if (minutes < 60) return `${minutes} minute${minutes > 1 ? "s" : ""}`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
}

/**
 * Parse a `Retry-After` header (delta-seconds or HTTP date) into seconds.
 * Returns null when absent or unparsable.
 */
export function parseRetryAfter(value: string | null | undefined, now: number = Date.now()): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^\d+(\.\d+)?$/.test(trimmed)) return Math.max(0, Math.ceil(Number(trimmed)));
  const date = Date.parse(trimmed);
  if (Number.isNaN(date)) return null;
  return Math.max(0, Math.ceil((date - now) / 1000));
}

function defaultFor(status: number): { code: string; detail: string } {
  const known = DEFAULT_MESSAGES[status];
  if (known) return known;
  if (status >= 500) {
    return {
      code: "server_error",
      detail:
        status === 502 || status === 503 || status === 504
          ? "Le service ORBIT est momentanément indisponible. Réessayez dans quelques instants."
          : "Erreur interne du serveur ORBIT.",
    };
  }
  return { code: "http_error", detail: `Erreur HTTP ${status}.` };
}

interface FastApiValidationIssue {
  loc?: Array<string | number>;
  msg?: string;
  type?: string;
}

function isValidationIssueArray(value: unknown): value is FastApiValidationIssue[] {
  return Array.isArray(value) && value.every((v) => typeof v === "object" && v !== null && "msg" in v);
}

/** Build an ApiError from a non-OK response. */
async function toApiError(response: Response): Promise<ApiError> {
  const fallback = defaultFor(response.status);
  let body: unknown = undefined;
  const contentType = response.headers.get("content-type") ?? "";
  try {
    body = contentType.includes("application/json") ? await response.json() : await response.text();
  } catch {
    body = undefined;
  }

  let detail = fallback.detail;
  let code = fallback.code;
  const fieldErrors: Record<string, string> = {};

  // Non-JSON 5xx (proxy cannot reach the backend, or an unhandled crash upstream).
  if (response.status >= 500 && !contentType.includes("application/json")) {
    return new ApiError({
      status: response.status,
      code: "service_unavailable",
      detail: "Le service ORBIT est momentanément indisponible. Réessayez dans quelques instants.",
      body,
    });
  }

  let retryAfter = parseRetryAfter(response.headers.get("retry-after"));

  if (body && typeof body === "object") {
    const record = body as Partial<ApiErrorBody> & { detail?: unknown; errors?: unknown; retry_after?: unknown };
    if (retryAfter === null && typeof record.retry_after === "number" && Number.isFinite(record.retry_after)) {
      retryAfter = Math.max(0, Math.ceil(record.retry_after));
    }
    if (typeof record.code === "string" && record.code) code = record.code;
    if (typeof record.detail === "string" && record.detail.trim()) {
      detail = record.detail;
    } else if (isValidationIssueArray(record.detail)) {
      for (const issue of record.detail) {
        const loc = (issue.loc ?? []).filter((p) => p !== "body" && p !== "query" && p !== "path");
        const field = loc.map(String).join(".");
        if (field && issue.msg && !fieldErrors[field]) fieldErrors[field] = issue.msg;
      }
      const first = record.detail[0];
      if (first?.msg) detail = `${fallback.detail} ${first.msg}`.trim();
    }
    if (record.errors && typeof record.errors === "object" && !Array.isArray(record.errors)) {
      for (const [k, v] of Object.entries(record.errors as Record<string, unknown>)) {
        if (typeof v === "string") fieldErrors[k] = v;
      }
    }
  }

  if (response.status === 429 && retryAfter !== null && retryAfter > 0 && detail === fallback.detail) {
    detail = `Trop de requêtes. Réessayez dans ${formatRetryDelay(retryAfter)}.`;
  }

  return new ApiError({ status: response.status, code, detail, fieldErrors, body, retryAfter });
}

/** Serialize query params (arrays → repeated keys; null/undefined/"" skipped). */
export function buildQuery(query?: QueryParams): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const v of value) params.append(key, String(v));
    } else {
      params.append(key, String(value));
    }
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

/** Absolute-path URL for an API path (useful for <a href> downloads). */
export function apiUrl(path: string, query?: QueryParams): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${normalized}${buildQuery(query)}`;
}

let redirecting = false;

/** Send the browser to /login, preserving the current location in `?next=`. */
export function redirectToLogin(): void {
  if (typeof window === "undefined" || redirecting) return;
  const { pathname, search } = window.location;
  if (pathname.startsWith("/login")) return;
  redirecting = true;
  const next = `${pathname}${search}`;
  const target = next && next !== "/" ? `/login?next=${encodeURIComponent(next)}` : "/login";
  window.location.assign(target);
}

/* -------------------------------------------------------------------------- */
/* CSRF (double submit)                                                       */
/* -------------------------------------------------------------------------- */

let csrfToken: string | null = null;
let csrfPromise: Promise<string | null> | null = null;

/** Value of the readable CSRF cookie (`orbit_csrf`, or its `__Host-` variant), if any. */
export function readCsrfCookie(): string | null {
  if (typeof document === "undefined" || !document.cookie) return null;
  for (const part of document.cookie.split(";")) {
    const [rawName, ...rest] = part.trim().split("=");
    if (rawName === CSRF_COOKIE || rawName === `__Host-${CSRF_COOKIE}`) {
      const value = rest.join("=");
      if (value) {
        try {
          return decodeURIComponent(value);
        } catch {
          return value;
        }
      }
    }
  }
  return null;
}

/** Fetch a fresh token from `GET /auth/csrf` (deduplicated; network errors yield null). */
async function fetchCsrfToken(): Promise<string | null> {
  if (!csrfPromise) {
    csrfPromise = (async () => {
      try {
        const response = await fetch(apiUrl("/auth/csrf"), {
          method: "GET",
          headers: { Accept: "application/json" },
          credentials: "include",
          cache: "no-store",
        });
        if (!response.ok) return null;
        const data = (await response.json()) as { csrf_token?: unknown };
        const token = typeof data.csrf_token === "string" && data.csrf_token ? data.csrf_token : null;
        csrfToken = token;
        return token;
      } catch {
        return null;
      } finally {
        csrfPromise = null;
      }
    })();
  }
  return csrfPromise;
}

/**
 * Token to send with an unsafe request: the cookie wins (it is what the server compares against),
 * then the cached value, then a single `GET /auth/csrf`.
 */
export async function getCsrfToken(forceRefresh = false): Promise<string | null> {
  if (forceRefresh) {
    csrfToken = null;
    return fetchCsrfToken();
  }
  return readCsrfCookie() ?? csrfToken ?? fetchCsrfToken();
}

/** Forget the cached token (after login/logout the server may rotate it). */
export function resetCsrfToken(): void {
  csrfToken = null;
  csrfPromise = null;
}

/* -------------------------------------------------------------------------- */
/* Core request                                                               */
/* -------------------------------------------------------------------------- */

/** Core request function. */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const {
    method = "GET",
    query,
    json,
    formData,
    signal,
    headers,
    redirectOnUnauthorized = true,
    responseType = "json",
  } = options;

  const finalHeaders = new Headers(headers);
  finalHeaders.set("Accept", responseType === "json" ? "application/json" : "*/*");

  let body: BodyInit | undefined;
  if (formData) {
    body = formData; // browser sets the multipart boundary
  } else if (json !== undefined) {
    finalHeaders.set("Content-Type", "application/json");
    body = JSON.stringify(json);
  }

  const unsafe = UNSAFE_METHODS.has(method);
  const url = apiUrl(path, query);

  const send = async (forceCsrfRefresh: boolean): Promise<Response> => {
    if (unsafe) {
      const token = await getCsrfToken(forceCsrfRefresh);
      if (token) finalHeaders.set(CSRF_HEADER, token);
      else finalHeaders.delete(CSRF_HEADER);
    }
    try {
      return await fetch(url, {
        method,
        headers: finalHeaders,
        body,
        signal,
        credentials: "include",
        cache: "no-store",
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new ApiError({
        status: 0,
        code: "network_error",
        detail: "Impossible de joindre le serveur ORBIT. Vérifiez votre connexion.",
        body: error,
      });
    }
  };

  let response = await send(false);
  let apiError: ApiError | null = response.ok ? null : await toApiError(response);

  // Stale or missing CSRF token: refresh it and replay the request exactly once.
  if (apiError?.isCsrfFailure && unsafe) {
    response = await send(true);
    apiError = response.ok ? null : await toApiError(response);
  }

  if (apiError) {
    if (apiError.status === 401 && redirectOnUnauthorized) redirectToLogin();
    throw apiError;
  }

  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return undefined as T;
  }

  switch (responseType) {
    case "text":
      return (await response.text()) as T;
    case "blob":
      return (await response.blob()) as T;
    default: {
      const text = await response.text();
      if (!text) return undefined as T;
      try {
        return JSON.parse(text) as T;
      } catch {
        throw new ApiError({
          status: response.status,
          code: "invalid_response",
          detail: "Réponse du serveur illisible.",
          body: text,
        });
      }
    }
  }
}

/** Convenience verbs. */
export const http = {
  get: <T>(path: string, options?: Omit<RequestOptions, "method" | "json" | "formData">) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, json?: unknown, options?: Omit<RequestOptions, "method" | "json">) =>
    request<T>(path, { ...options, method: "POST", json }),
  patch: <T>(path: string, json?: unknown, options?: Omit<RequestOptions, "method" | "json">) =>
    request<T>(path, { ...options, method: "PATCH", json }),
  delete: <T = void>(path: string, options?: Omit<RequestOptions, "method">) =>
    request<T>(path, { ...options, method: "DELETE" }),
  upload: <T>(path: string, formData: FormData, options?: Omit<RequestOptions, "method" | "formData" | "json">) =>
    request<T>(path, { ...options, method: "POST", formData }),
};

/** Trigger a browser download for a Blob. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
