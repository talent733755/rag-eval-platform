import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { IngestionJobStatus } from "../src/components/documents/ingestion-job-status";
import type { createApiClient } from "../src/lib/api/client";

const projectId = "11111111-1111-4111-8111-111111111111";
const documentId = "22222222-2222-4222-8222-222222222222";

function makeDocument() {
  return {
    id: documentId,
    display_name: "说明.md",
    source_type: "markdown",
    archived_at: null,
    latest_version: {
      id: "33333333-3333-4333-8333-333333333333",
      version_number: 1,
      parse_status: "failed",
      sha256: "a".repeat(64),
      parser_version: "markdown-v1",
      parse_error_code: "parser_failed",
    },
  } as never;
}

function makeJob(status: string) {
  return {
    id: "44444444-4444-4444-8444-444444444444",
    status,
    job_kind: "parse",
    attempt_count: 1,
    completed_units: 0,
    total_units: 1,
    last_error_code: status === "failed" ? "parser_failed" : null,
    cancel_requested_at: null,
    document_version_id: "33333333-3333-4333-8333-333333333333",
    candidate_dataset_id: null,
    organization_id: "org",
    project_id: projectId,
    idempotency_key: "key",
  } as never;
}

describe("IngestionJobStatus", () => {
  afterEach(cleanup);

  it("retries a failed job and reports the change", async () => {
    const client = {
      retryParse: vi.fn().mockResolvedValue(makeJob("queued")),
      cancelIngestionJob: vi.fn(),
    };
    const onChanged = vi.fn();
    render(
      <IngestionJobStatus
        client={client as unknown as ReturnType<typeof createApiClient>}
        projectId={projectId}
        documentId={documentId}
        document={makeDocument()}
        job={makeJob("failed")}
        onChanged={onChanged}
      />,
    );

    expect(screen.getByText("任务失败")).toBeInTheDocument();
    expect(screen.getByText(/失败码：parser_failed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试解析" }));

    await waitFor(() => expect(client.retryParse).toHaveBeenCalledWith(projectId, documentId, "33333333-3333-4333-8333-333333333333"));
    expect(onChanged).toHaveBeenCalled();
    await waitFor(() => expect(screen.getByText("任务处理中")).toBeInTheDocument());
  });

  it("cancels an in-flight job", async () => {
    const client = {
      retryParse: vi.fn(),
      cancelIngestionJob: vi.fn().mockResolvedValue(makeJob("cancelled")),
    };
    render(
      <IngestionJobStatus
        client={client as unknown as ReturnType<typeof createApiClient>}
        projectId={projectId}
        documentId={documentId}
        document={makeDocument()}
        job={makeJob("processing")}
        onChanged={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "取消任务" }));
    await waitFor(() => expect(client.cancelIngestionJob).toHaveBeenCalledWith(projectId, "44444444-4444-4444-8444-444444444444"));
    await waitFor(() => expect(screen.getByText("任务已取消")).toBeInTheDocument());
  });

  it("shows a safe error when retry fails", async () => {
    const client = {
      retryParse: vi.fn().mockRejectedValue(new Error("网络不可用")),
      cancelIngestionJob: vi.fn(),
    };
    render(
      <IngestionJobStatus
        client={client as unknown as ReturnType<typeof createApiClient>}
        projectId={projectId}
        documentId={documentId}
        document={makeDocument()}
        job={makeJob("failed")}
        onChanged={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "重试解析" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("网络不可用"));
  });
});
