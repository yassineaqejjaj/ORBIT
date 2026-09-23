/**
 * Minimal, typed fetch wrapper for the ORBIT REST API.
 *
 * - Same-origin calls to `/api/v1/...` (Next.js rewrites proxy them to FastAPI), `credentials: "include"`.
 * - JSON and multipart bodies, query-string serialization.
 * - Errors are normalized to `ApiError` (`status`, `code`, `detail`, optional `fieldErrors`).
 * - 401 → redirect to `/login?next=<current path>` (opt-out with `redirectOnUnauthorized: false`).
 */
import type { ApiErrorBody } from "./types";

export const API_BASE = "/api/v1";

export type QueryValue = string | number | boolean | null | undefined | ReadonlyArray<string | number>;
export type QueryParams = Record<string, QueryValue>;

export type HttpMethod = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

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

  constructor(init: {
    status: number;
    code: string;
    detail: string;
    fieldErrors?: Record<string, string>;
    body?: unknown;
  }) {
    super(init.detail);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.detail = init.detail;
    this.fieldErrors = init.fieldErrors ?? {};
    this.body = init.body;
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

  if (body && typeof body === "object") {
    const record = body as Partial<ApiErrorBody> & { detail?: unknown; errors?: unknown };
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

  return new ApiError({ status: response.status, code, detail, fieldErrors, body });
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

  let response: Response;
  try {
    response = await fetch(apiUrl(path, query), {
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

  if (!response.ok) {
    const apiError = await toApiError(response);
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
