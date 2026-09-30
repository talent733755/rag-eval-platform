export type DocumentRow = {
  id: string;
  display_name: string;
  source_type: string;
  latest_version?: {
    version_number: number;
    parse_status?: string;
    sha256?: string;
    parser_version?: string | null;
    parse_error_code?: string | null;
  } | null;
  archived_at?: string | null;
  [key: string]: unknown;
};

export type UploadOutcome = {
  client_id: string;
  status: string;
  response?: { document: { id: string }; ingestion_job: { id: string } } | null;
  error?: { code: string; message: string } | null;
};

export type DocumentsState = {
  items: DocumentRow[];
  summary: Record<string, number>;
  nextCursor: string | null;
  listState: "idle" | "loading" | "success" | "error";
  error: string | null;
  uploadState: "idle" | "uploading" | "success" | "partial" | "error";
  uploadMessage: string | null;
  jobsByDocument: Record<string, string>;
};

export const initialDocumentsState: DocumentsState = {
  items: [],
  summary: { total: 0 },
  nextCursor: null,
  listState: "idle",
  error: null,
  uploadState: "idle",
  uploadMessage: null,
  jobsByDocument: {},
};

export type DocumentsAction =
  | { type: "list_started" }
  | { type: "list_succeeded"; items: DocumentRow[]; summary: Record<string, number>; nextCursor: string | null }
  | { type: "list_failed"; message: string }
  | { type: "upload_started" }
  | { type: "upload_rejected"; message: string }
  | { type: "upload_finished"; outcomes: UploadOutcome[] }
  | { type: "upload_failed"; message: string }
  | { type: "job_associated"; documentId: string; jobId: string }
  | { type: "job_updated"; documentId: string; status: string };

const TERMINAL_JOB_STATUSES = new Set(["succeeded", "failed", "cancelled"]);

export function documentsReducer(state: DocumentsState, action: DocumentsAction): DocumentsState {
  switch (action.type) {
    case "list_started":
      return { ...state, listState: "loading", error: null };
    case "list_succeeded":
      return {
        ...state,
        listState: "success",
        items: action.items,
        summary: action.summary,
        nextCursor: action.nextCursor,
        error: null,
      };
    case "list_failed":
      return { ...state, listState: "error", error: action.message };
    case "upload_started":
      return { ...state, uploadState: "uploading", uploadMessage: null };
    case "upload_rejected":
    case "upload_failed":
      return { ...state, uploadState: "error", uploadMessage: action.message };
    case "upload_finished": {
      const failed = action.outcomes.filter((outcome) => outcome.status === "failed");
      const jobsByDocument = { ...state.jobsByDocument };
      for (const outcome of action.outcomes) {
        const documentId = outcome.response?.document.id;
        const jobId = outcome.response?.ingestion_job.id;
        if (documentId && jobId) {
          jobsByDocument[documentId] = jobId;
        }
      }
      return {
        ...state,
        uploadState: failed.length > 0 ? "partial" : "success",
        uploadMessage:
          failed.length > 0
            ? `${failed.length} 个文件上传失败，请查看详情。`
            : `已提交 ${action.outcomes.length} 个文件，解析任务已排队。`,
        jobsByDocument,
      };
    }
    case "job_associated":
      return {
        ...state,
        jobsByDocument: { ...state.jobsByDocument, [action.documentId]: action.jobId },
      };
    case "job_updated": {
      if (!TERMINAL_JOB_STATUSES.has(action.status)) return state;
      if (!(action.documentId in state.jobsByDocument)) return state;
      const jobsByDocument = { ...state.jobsByDocument };
      delete jobsByDocument[action.documentId];
      return { ...state, jobsByDocument };
    }
  }
}
