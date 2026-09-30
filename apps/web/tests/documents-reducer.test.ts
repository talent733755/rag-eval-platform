import { describe, expect, it } from "vitest";

import {
  documentsReducer,
  initialDocumentsState,
  type DocumentRow,
  type UploadOutcome,
} from "../src/lib/documents/reducer";

function row(id: string, parseStatus = "succeeded"): DocumentRow {
  return {
    id,
    display_name: `${id}.md`,
    source_type: "markdown",
    latest_version: { version_number: 1, parse_status: parseStatus },
  };
}

describe("documentsReducer", () => {
  it("transitions list loading to success with items, summary, and cursor", () => {
    const loading = documentsReducer(initialDocumentsState, { type: "list_started" });
    expect(loading.listState).toBe("loading");
    expect(loading.error).toBeNull();

    const loaded = documentsReducer(loading, {
      type: "list_succeeded",
      items: [row("doc-1")],
      summary: { total: 1 },
      nextCursor: "cursor-2",
    });
    expect(loaded.listState).toBe("success");
    expect(loaded.items).toHaveLength(1);
    expect(loaded.summary).toEqual({ total: 1 });
    expect(loaded.nextCursor).toBe("cursor-2");
    expect(loaded.error).toBeNull();
  });

  it("records a safe error message when the list fails", () => {
    const failed = documentsReducer(
      { ...initialDocumentsState, items: [row("doc-1")] },
      { type: "list_failed", message: "文档加载失败" },
    );
    expect(failed.listState).toBe("error");
    expect(failed.error).toBe("文档加载失败");
    expect(failed.items).toHaveLength(1);
  });

  it("tracks upload progress and per-file outcomes", () => {
    const uploading = documentsReducer(initialDocumentsState, { type: "upload_started" });
    expect(uploading.uploadState).toBe("uploading");
    expect(uploading.uploadMessage).toBeNull();

    const outcomes: UploadOutcome[] = [
      { client_id: "a.md", status: "accepted", response: { document: { id: "doc-a" }, ingestion_job: { id: "job-a" } } },
      { client_id: "b.md", status: "failed", response: null, error: { code: "duplicate_document", message: "内容重复" } },
    ];
    const finished = documentsReducer(uploading, { type: "upload_finished", outcomes });
    expect(finished.uploadState).toBe("partial");
    expect(finished.jobsByDocument).toEqual({ "doc-a": "job-a" });
    expect(finished.uploadMessage).toContain("1");
  });

  it("marks a fully accepted upload as success", () => {
    const outcomes: UploadOutcome[] = [
      { client_id: "a.md", status: "accepted", response: { document: { id: "doc-a" }, ingestion_job: { id: "job-a" } } },
    ];
    const finished = documentsReducer(
      documentsReducer(initialDocumentsState, { type: "upload_started" }),
      { type: "upload_finished", outcomes },
    );
    expect(finished.uploadState).toBe("success");
    expect(finished.uploadMessage).toContain("1");
  });

  it("fails upload state when the batch request itself errors", () => {
    const failed = documentsReducer(
      documentsReducer(initialDocumentsState, { type: "upload_started" }),
      { type: "upload_failed", message: "文件上传失败" },
    );
    expect(failed.uploadState).toBe("error");
    expect(failed.uploadMessage).toBe("文件上传失败");
  });

  it("rejects batches over the 20 file limit before any request", () => {
    const rejected = documentsReducer(initialDocumentsState, { type: "upload_rejected", message: "一次最多上传 20 个文件。" });
    expect(rejected.uploadState).toBe("error");
    expect(rejected.uploadMessage).toBe("一次最多上传 20 个文件。");
  });

  it("associates a job with only its own document row", () => {
    const withJob = documentsReducer(initialDocumentsState, {
      type: "job_associated",
      documentId: "doc-1",
      jobId: "job-1",
    });
    expect(withJob.jobsByDocument).toEqual({ "doc-1": "job-1" });

    const withSecond = documentsReducer(withJob, {
      type: "job_associated",
      documentId: "doc-2",
      jobId: "job-2",
    });
    expect(withSecond.jobsByDocument).toEqual({ "doc-1": "job-1", "doc-2": "job-2" });
  });

  it("stops tracking a job once it reaches a terminal status", () => {
    const tracked = documentsReducer(initialDocumentsState, {
      type: "job_associated",
      documentId: "doc-1",
      jobId: "job-1",
    });
    const stillPolling = documentsReducer(tracked, { type: "job_updated", documentId: "doc-1", status: "processing" });
    expect(stillPolling.jobsByDocument).toEqual({ "doc-1": "job-1" });

    const finished = documentsReducer(tracked, { type: "job_updated", documentId: "doc-1", status: "succeeded" });
    expect(finished.jobsByDocument).toEqual({});
  });

  it("replaces the current list while preserving the cursor on refresh", () => {
    const current = {
      ...initialDocumentsState,
      items: [row("doc-1")],
      summary: { total: 1 },
      nextCursor: "cursor-2" as string | null,
    };
    const refreshed = documentsReducer(current, {
      type: "list_succeeded",
      items: [row("doc-2", "queued")],
      summary: { total: 2 },
      nextCursor: null,
    });
    expect(refreshed.items[0]?.id).toBe("doc-2");
    expect(refreshed.nextCursor).toBeNull();
  });
});
