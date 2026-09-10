import type { components, operations } from "./generated";

const DEFAULT_API_BASE_URL = "http://localhost:8000";

type ProjectListResponse =
  operations["list_projects_api_projects_get"]["responses"][200]["content"]["application/json"];

type ErrorEnvelope = {
  error?: {
    code?: unknown;
    message?: unknown;
  };
};

type FetchLike = typeof fetch;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type ApiClient = {
  listProjects(options?: { signal?: AbortSignal }): Promise<ProjectListResponse>;
};

export function createApiClient({
  baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL,
  fetchImpl = fetch,
}: {
  baseUrl?: string;
  fetchImpl?: FetchLike;
} = {}): ApiClient {
  const normalizedBaseUrl = baseUrl.replace(/\/$/, "");

  return {
    async listProjects(options) {
      return requestJson<ProjectListResponse>(
        `${normalizedBaseUrl}/api/projects`,
        { method: "GET", signal: options?.signal },
        fetchImpl,
      );
    },
  };
}

export type ProjectResponse = components["schemas"]["ProjectResponse"];

async function requestJson<T>(url: string, init: RequestInit, fetchImpl: FetchLike): Promise<T> {
  const response = await fetchImpl(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init.headers,
    },
  });

  if (!response.ok) {
    throw await createApiError(response);
  }

  return (await response.json()) as T;
}

async function createApiError(response: Response): Promise<ApiError> {
  let envelope: ErrorEnvelope = {};
  try {
    envelope = (await response.json()) as ErrorEnvelope;
  } catch {
    // Preserve the status even when a proxy returns a non-JSON error page.
  }

  const code = typeof envelope.error?.code === "string" ? envelope.error.code : "http_error";
  const message =
    typeof envelope.error?.message === "string"
      ? envelope.error.message
      : `API request failed with status ${response.status}`;

  return new ApiError(response.status, code, message);
}
