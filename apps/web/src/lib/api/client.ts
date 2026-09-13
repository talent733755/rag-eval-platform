import type { components, operations } from "./generated";

const DEFAULT_API_BASE_URL = "http://localhost:8000";

type ProjectListResponse =
  operations["list_projects_api_projects_get"]["responses"][200]["content"]["application/json"];
type DocumentListResponse = components["schemas"]["DocumentListResponse"];
type DocumentResponse = components["schemas"]["DocumentResponse"];
type DocumentJobResponse = components["schemas"]["DocumentJobResponse"];
type BatchUploadResponse = components["schemas"]["DocumentBatchUploadResponse"];
type CandidateDatasetResponse = components["schemas"]["CandidateDatasetResponse"];
type CandidateDatasetVersionResponse = components["schemas"]["CandidateDatasetVersionResponse"];
type CandidateItemResponse = components["schemas"]["CandidateItemResponse"];
type CandidateReviewRequest = components["schemas"]["CandidateReviewRequest"];
type CandidateGenerationRequest = components["schemas"]["CandidateGenerationRequest"];
type CandidateGenerationJobResponse = components["schemas"]["CandidateGenerationJobResponse"];
type AdapterConfig = components["schemas"]["AdapterConfigResponse"];
type AdapterConfigCreate = components["schemas"]["AdapterConfigCreate"];
type AdapterConfigUpdate = components["schemas"]["AdapterConfigUpdate"];
type ModelProviderConfig = components["schemas"]["ModelProviderResponse"];
type ExperimentDraftRequest = components["schemas"]["ExperimentDraftRequest"];
type ExperimentResponse = components["schemas"]["ExperimentResponse"];
type ExperimentStartResponse = components["schemas"]["ExperimentStartResponse"];
type ExperimentRunResponse = components["schemas"]["ExperimentRunResponse"];
type ExperimentRunItemResponse = components["schemas"]["ExperimentRunItemResponse"];
type MetricDefinitionResponse = components["schemas"]["MetricDefinitionResponse"];
type MetricResultResponse = components["schemas"]["MetricResultResponse"];

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
  getDocument(projectId: string, documentId: string, options?: { signal?: AbortSignal }): Promise<DocumentResponse>;
  getIngestionJob(projectId: string, jobId: string, options?: { signal?: AbortSignal }): Promise<DocumentJobResponse>;
  retryParse(projectId: string, documentId: string, versionId: string, options?: { signal?: AbortSignal; idempotencyKey?: string }): Promise<DocumentJobResponse>;
  cancelIngestionJob(projectId: string, jobId: string, options?: { signal?: AbortSignal }): Promise<DocumentJobResponse>;
  archiveDocument(projectId: string, documentId: string, confirmReferenced?: boolean, options?: { signal?: AbortSignal }): Promise<DocumentResponse>;
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
  generateCandidates(projectId: string, documentId: string, payload: CandidateGenerationRequest, options?: { signal?: AbortSignal; idempotencyKey?: string }): Promise<CandidateGenerationJobResponse>;
  listAdapters(projectId: string, options?: { signal?: AbortSignal }): Promise<AdapterConfig[]>;
  createAdapter(projectId: string, payload: AdapterConfigCreate, options?: { signal?: AbortSignal }): Promise<AdapterConfig>;
  getAdapter(projectId: string, adapterId: string, options?: { signal?: AbortSignal }): Promise<AdapterConfig>;
  updateAdapter(projectId: string, adapterId: string, payload: AdapterConfigUpdate, options?: { signal?: AbortSignal }): Promise<AdapterConfig>;
  deleteAdapter(projectId: string, adapterId: string, options?: { signal?: AbortSignal }): Promise<void>;
  testAdapter(projectId: string, adapterId: string, options?: { signal?: AbortSignal }): Promise<AdapterConfig>;
  listModelProviders(projectId: string, options?: { signal?: AbortSignal }): Promise<ModelProviderConfig[]>;
  listExperiments(projectId: string, options?: { signal?: AbortSignal }): Promise<ExperimentResponse[]>;
  createExperiment(projectId: string, payload: ExperimentDraftRequest, options?: { signal?: AbortSignal; idempotencyKey?: string }): Promise<ExperimentResponse>;
  startExperiment(projectId: string, experimentId: string, options?: { signal?: AbortSignal }): Promise<ExperimentStartResponse>;
  listExperimentRuns(projectId: string, experimentId: string, options?: { signal?: AbortSignal }): Promise<ExperimentRunResponse[]>;
  cancelExperimentRun(projectId: string, runId: string, options?: { signal?: AbortSignal }): Promise<ExperimentRunResponse>;
  listExperimentRunItems(projectId: string, runId: string, options?: { signal?: AbortSignal }): Promise<ExperimentRunItemResponse[]>;
  retryExperimentRunItem(projectId: string, runId: string, itemId: string, options?: { signal?: AbortSignal }): Promise<ExperimentRunItemResponse>;
  listMetricDefinitions(projectId: string, options?: { signal?: AbortSignal }): Promise<MetricDefinitionResponse[]>;
  listExperimentMetrics(projectId: string, experimentId: string, options?: { signal?: AbortSignal }): Promise<MetricResultResponse[]>;
  listRunMetrics(projectId: string, experimentId: string, runId: string, options?: { signal?: AbortSignal }): Promise<MetricResultResponse[]>;
  listSampleMetrics(projectId: string, experimentId: string, runId: string, itemId: string, options?: { signal?: AbortSignal }): Promise<MetricResultResponse[]>;
  recalculateRunMetrics(projectId: string, experimentId: string, runId: string, options?: { signal?: AbortSignal }): Promise<MetricResultResponse[]>;
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
    async getDocument(projectId, documentId, options) {
      return requestJson<DocumentResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async getIngestionJob(projectId, jobId, options) {
      return requestJson<DocumentJobResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/ingestion-jobs/${encodeURIComponent(jobId)}`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async retryParse(projectId, documentId, versionId, options) {
      return requestJson<DocumentJobResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/retry-parse`,
        { method: "POST", signal: options?.signal, headers: { "Idempotency-Key": options?.idempotencyKey ?? createIdempotencyKey() } }, fetchImpl,
      );
    },
    async cancelIngestionJob(projectId, jobId, options) {
      return requestJson<DocumentJobResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/ingestion-jobs/${encodeURIComponent(jobId)}/cancel`,
        { method: "POST", signal: options?.signal }, fetchImpl,
      );
    },
    async archiveDocument(projectId, documentId, confirmReferenced = false, options) {
      return requestJson<DocumentResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}/archive`,
        { method: "POST", body: JSON.stringify({ confirm_referenced: confirmReferenced }), signal: options?.signal, headers: { "Content-Type": "application/json" } }, fetchImpl,
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
    async generateCandidates(projectId, documentId, payload, options) {
      return requestJson<CandidateGenerationJobResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}/generate-candidates`,
        {
          method: "POST",
          body: JSON.stringify(payload),
          signal: options?.signal,
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": options?.idempotencyKey ?? createIdempotencyKey(),
          },
        },
        fetchImpl,
      );
    },
    async listAdapters(projectId, options) {
      return requestJson<AdapterConfig[]>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/adapters`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async createAdapter(projectId, payload, options) {
      return requestJson<AdapterConfig>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/adapters`,
        { method: "POST", body: JSON.stringify(payload), signal: options?.signal, headers: { "Content-Type": "application/json" } }, fetchImpl,
      );
    },
    async getAdapter(projectId, adapterId, options) {
      return requestJson<AdapterConfig>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/adapters/${encodeURIComponent(adapterId)}`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async updateAdapter(projectId, adapterId, payload, options) {
      return requestJson<AdapterConfig>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/adapters/${encodeURIComponent(adapterId)}`,
        { method: "PATCH", body: JSON.stringify(payload), signal: options?.signal, headers: { "Content-Type": "application/json" } }, fetchImpl,
      );
    },
    async deleteAdapter(projectId, adapterId, options) {
      await requestNoContent(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/adapters/${encodeURIComponent(adapterId)}`,
        { method: "DELETE", signal: options?.signal }, fetchImpl,
      );
    },
    async testAdapter(projectId, adapterId, options) {
      return requestJson<AdapterConfig>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/adapters/${encodeURIComponent(adapterId)}/test`,
        { method: "POST", signal: options?.signal }, fetchImpl,
      );
    },
    async listModelProviders(projectId, options) {
      return requestJson<ModelProviderConfig[]>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/model-providers`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async listExperiments(projectId, options) {
      return requestJson<ExperimentResponse[]>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/experiments`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async createExperiment(projectId, payload, options) {
      return requestJson<ExperimentResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/experiments`,
        { method: "POST", body: JSON.stringify(payload), signal: options?.signal, headers: { "Content-Type": "application/json", "Idempotency-Key": options?.idempotencyKey ?? createIdempotencyKey() } }, fetchImpl,
      );
    },
    async startExperiment(projectId, experimentId, options) {
      return requestJson<ExperimentStartResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/experiments/${encodeURIComponent(experimentId)}/start`,
        { method: "POST", signal: options?.signal }, fetchImpl,
      );
    },
    async listExperimentRuns(projectId, experimentId, options) {
      return requestJson<ExperimentRunResponse[]>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/experiments/${encodeURIComponent(experimentId)}/runs`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async cancelExperimentRun(projectId, runId, options) {
      return requestJson<ExperimentRunResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/experiments/runs/${encodeURIComponent(runId)}/cancel`,
        { method: "POST", signal: options?.signal }, fetchImpl,
      );
    },
    async listExperimentRunItems(projectId, runId, options) {
      return requestJson<ExperimentRunItemResponse[]>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/experiments/runs/${encodeURIComponent(runId)}/items`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async retryExperimentRunItem(projectId, runId, itemId, options) {
      return requestJson<ExperimentRunItemResponse>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/experiments/runs/${encodeURIComponent(runId)}/items/${encodeURIComponent(itemId)}/retry`,
        { method: "POST", signal: options?.signal }, fetchImpl,
      );
    },
    async listMetricDefinitions(projectId, options) {
      return requestJson<MetricDefinitionResponse[]>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/metric-definitions`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async listExperimentMetrics(projectId, experimentId, options) {
      return requestJson<MetricResultResponse[]>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/experiments/${encodeURIComponent(experimentId)}/metrics`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async listRunMetrics(projectId, experimentId, runId, options) {
      return requestJson<MetricResultResponse[]>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/experiments/${encodeURIComponent(experimentId)}/runs/${encodeURIComponent(runId)}/metrics`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async listSampleMetrics(projectId, experimentId, runId, itemId, options) {
      return requestJson<MetricResultResponse[]>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/experiments/${encodeURIComponent(experimentId)}/runs/${encodeURIComponent(runId)}/items/${encodeURIComponent(itemId)}/metrics`,
        { method: "GET", signal: options?.signal }, fetchImpl,
      );
    },
    async recalculateRunMetrics(projectId, experimentId, runId, options) {
      return requestJson<MetricResultResponse[]>(
        `${normalizedBaseUrl}/api/projects/${encodeURIComponent(projectId)}/experiments/${encodeURIComponent(experimentId)}/runs/${encodeURIComponent(runId)}/metrics/recalculate`,
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

async function requestNoContent(url: string, init: RequestInit, fetchImpl: FetchLike): Promise<void> {
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
