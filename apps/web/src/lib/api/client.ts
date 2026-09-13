import type { components, operations } from "./generated";

const DEFAULT_API_BASE_URL = "http://localhost:8000";

type ProjectListResponse =
  operations["list_projects_api_projects_get"]["responses"][200]["content"]["application/json"];
type DocumentListResponse = components["schemas"]["DocumentListResponse"];
type BatchUploadResponse = components["schemas"]["DocumentBatchUploadResponse"];
type CandidateDatasetResponse = components["schemas"]["CandidateDatasetResponse"];
type CandidateDatasetVersionResponse = components["schemas"]["CandidateDatasetVersionResponse"];
type CandidateItemResponse = components["schemas"]["CandidateItemResponse"];
type CandidateReviewRequest = components["schemas"]["CandidateReviewRequest"];

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
  listDocuments(
    projectId: string,
    options?: {
      query?: { q?: string; source_type?: string; parse_status?: string; cursor?: string };
      signal?: AbortSignal;
    },
  ): Promise<DocumentListResponse>;
  uploadDocuments(
    projectId: string,
    files: File[],
    options?: { signal?: AbortSignal; idempotencyKey?: string },
  ): Promise<BatchUploadResponse>;
  listCandidateDatasets(projectId: string, options?: { signal?: AbortSignal }): Promise<CandidateDatasetResponse[]>;
  listCandidateDatasetVersions(projectId: string, datasetId: string, options?: { signal?: AbortSignal }): Promise<CandidateDatasetVersionResponse[]>;
  listCandidateItems(projectId: string, datasetId: string, versionId: string, options?: { signal?: AbortSignal }): Promise<CandidateItemResponse[]>;
  reviewCandidateItem(projectId: string, datasetId: string, versionId: string, payload: CandidateReviewRequest, options?: { signal?: AbortSignal }): Promise<CandidateItemResponse>;
  publishCandidateDatasetVersion(projectId: string, datasetId: string, versionId: string, options?: { signal?: AbortSignal }): Promise<CandidateDatasetVersionResponse>;
  archiveCandidateDatasetVersion(projectId: string, datasetId: string, versionId: string, options?: { signal?: AbortSignal }): Promise<CandidateDatasetVersionResponse>;
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
    async listDocuments(projectId, options) {
      const query = new URLSearchParams();
      for (const [key, value] of Object.entries(options?.query ?? {})) {
        if (value) query.set(key, value);
      }
      const suffix = query.toString() ? `?${query.toString()}` : "";
      return requestJson<DocumentListResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/documents${suffix}`,
        { method: "GET", signal: options?.signal },
        fetchImpl,
      );
    },
    async uploadDocuments(projectId, files, options) {
      const formData = new FormData();
      for (const file of files) formData.append("files", file, file.name);
      return requestJson<BatchUploadResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/documents/batch-upload`,
        {
          method: "POST",
          body: formData,
          signal: options?.signal,
          headers: { "Idempotency-Key": options?.idempotencyKey ?? createIdempotencyKey() },
        },
        fetchImpl,
      );
    },
    async listCandidateDatasets(projectId, options) {
      return requestJson<CandidateDatasetResponse[]>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/candidate-datasets`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async listCandidateDatasetVersions(projectId, datasetId, options) {
      return requestJson<CandidateDatasetVersionResponse[]>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/candidate-datasets/${encodeURIComponent(datasetId)}/versions`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async listCandidateItems(projectId, datasetId, versionId, options) {
      return requestJson<CandidateItemResponse[]>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/candidate-datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/items`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async reviewCandidateItem(projectId, datasetId, versionId, payload, options) {
      return requestJson<CandidateItemResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/candidate-datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/review`,
        { method: "POST", body: JSON.stringify(payload), signal: options?.signal, headers: { "Content-Type": "application/json" } }, fetchImpl,
      );
    },
    async publishCandidateDatasetVersion(projectId, datasetId, versionId, options) {
      return requestJson<CandidateDatasetVersionResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/candidate-datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/publish`,
        { method: "POST", signal: options?.signal }, fetchImpl,
      );
    },
    async archiveCandidateDatasetVersion(projectId, datasetId, versionId, options) {
      return requestJson<CandidateDatasetVersionResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/candidate-datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/archive`,
        { method: "POST", signal: options?.signal }, fetchImpl,
      );
    },
  };
}

function createIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
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
