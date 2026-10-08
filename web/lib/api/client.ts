/** Minimal typed fetch wrapper that unwraps the SETU-DRR error envelope. */

import type { ApiErrorEnvelope } from './types';

export function getApiBaseUrl(): string {
  if (process.env.NEXT_PUBLIC_API_BASE_URL) {
    return process.env.NEXT_PUBLIC_API_BASE_URL.replace(/\/$/, '');
  }
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host === 'localhost' || host === '127.0.0.1') {
      return 'http://localhost:8000';
    }
  }
  return 'https://the-dead-zone.onrender.com';
}

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, '') || 'http://localhost:8000';

/** Error carrying the machine-readable code and request id from the API envelope. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId: string | null;
  readonly details: Record<string, unknown>;

  constructor(
    message: string,
    status: number,
    code = 'INTERNAL_ERROR',
    requestId: string | null = null,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.requestId = requestId;
    this.details = details;
  }
}

function buildUrl(path: string, params?: Record<string, string | number | undefined>): string {
  // If path is already a fully-qualified URL
  if (/^https?:\/\//i.test(path)) {
    const url = new URL(path);
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null && value !== '') {
          url.searchParams.set(key, String(value));
        }
      }
    }
    return url.toString();
  }

  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  const base = getApiBaseUrl();

  let url: URL;
  if (/^https?:\/\//i.test(base)) {
    url = new URL(`${base}${cleanPath}`);
  } else if (typeof window !== 'undefined') {
    url = new URL(`${base}${cleanPath}`, window.location.origin);
  } else {
    // SSR / Node fallback origin for relative base paths
    url = new URL(`${base}${cleanPath}`, 'http://localhost:3000');
  }

  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function unwrapError(response: Response): Promise<ApiError> {
  let code = 'INTERNAL_ERROR';
  let message = `Request failed with status ${response.status}.`;
  let requestId: string | null = null;
  let details: Record<string, unknown> = {};
  try {
    const body = (await response.json()) as ApiErrorEnvelope | { detail?: string };
    if ('error' in body && body.error) {
      code = body.error.code;
      message = body.error.message;
      requestId = body.error.request_id;
      details = body.error.details ?? {};
    } else if ('detail' in body && body.detail) {
      message = body.detail;
    }
  } catch {
    // Non-JSON error body — keep the status-derived message.
  }
  return new ApiError(message, response.status, code, requestId, details);
}

const TOKEN_STORAGE_KEY = 'setu_auth_token';

/** Retrieves persisted access token from localStorage for cross-origin or non-cookie environments (e.g. Vercel). */
export function getStoredToken(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Stores or clears persisted access token in localStorage. */
export function setStoredToken(token: string | null): void {
  if (typeof window === 'undefined') return;
  try {
    if (token) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    // Storage access may be restricted in private browsing mode
  }
}

export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
  signal?: AbortSignal,
): Promise<T> {
  const token = getStoredToken();
  let response: Response;
  try {
    response = await fetch(buildUrl(path, params), {
      signal,
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    const targetUrl = getApiBaseUrl() || API_BASE_URL;
    throw new ApiError(
      `Cannot reach the TERRA API at ${targetUrl}. If the service was idle, Render may be waking up (cold start can take ~30-50s). Please wait a moment and retry.`,
      0,
      'NETWORK_ERROR',
    );
  }

  if (!response.ok) {
    throw await unwrapError(response);
  }

  return (await response.json()) as T;
}

export async function apiPost<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const token = getStoredToken();
  let response: Response;
  try {
    response = await fetch(buildUrl(path), {
      method: 'POST',
      signal,
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    const targetUrl = getApiBaseUrl() || API_BASE_URL;
    throw new ApiError(
      `Cannot reach the TERRA API at ${targetUrl}. If the service was idle, Render may be waking up (cold start can take ~30-50s). Please wait a moment and retry.`,
      0,
      'NETWORK_ERROR',
    );
  }

  if (!response.ok) {
    throw await unwrapError(response);
  }

  return (await response.json()) as T;
}

