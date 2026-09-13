import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentsWorkspace } from "../src/components/documents/documents-workspace";

const projectId = "11111111-1111-4111-8111-111111111111";

describe("DocumentsWorkspace", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", `/documents?project=${projectId}`);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads and renders the project document list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            items: [
              {
                id: "doc-1",
                display_name: "产品说明.md",
                source_type: "markdown",
                latest_version: { version_number: 2, parse_status: "succeeded" },
              },
            ],
            next_cursor: null,
            summary: { total: 1 },
          }),
          { status: 200 },
        ),
      ),
    );

    render(<DocumentsWorkspace />);

    expect(screen.getByText("正在加载文档…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("产品说明.md")).toBeInTheDocument());
    expect(screen.getAllByText("解析成功")).toHaveLength(2);
    expect(screen.getAllByText("1", { selector: "p" })).toHaveLength(2);
  });

  it("uploads selected files and reports the queued result", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [], next_cursor: null, summary: { total: 0 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ client_id: "说明.md", status: "queued", response: null }] }), { status: 207 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [], next_cursor: null, summary: { total: 0 } }), { status: 200 }));
    vi.stubGlobal("fetch", fetchImpl);

    render(<DocumentsWorkspace />);
    await waitFor(() => expect(screen.getByText("还没有文档。上传一份 PDF、Word、Markdown 或 TXT 后即可开始解析。")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("上传文档"), {
      target: { files: [new File(["内容"], "说明.md", { type: "text/markdown" })] },
    });

    await waitFor(() => expect(screen.getByText(/解析任务已排队/)).toBeInTheDocument());
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it("opens document details and polls the uploaded job until it succeeds", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [], next_cursor: null, summary: { total: 0 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ client_id: "说明.md", status: "accepted", response: { document: { id: "doc-1" }, ingestion_job: { id: "job-1" } } }] }), { status: 207 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: "doc-1", display_name: "说明.md", source_type: "markdown", latest_version: { version_number: 1, parse_status: "queued", sha256: "a".repeat(64) } }], next_cursor: null, summary: { total: 1 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "doc-1", display_name: "说明.md", source_type: "markdown", latest_version: { version_number: 1, parse_status: "queued", sha256: "a".repeat(64) } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-1", status: "succeeded", job_kind: "parse", attempt_count: 1, completed_units: 1, total_units: 1, cancel_requested_at: null, document_version_id: "version-1", candidate_dataset_id: null, last_error_code: null, organization_id: "org", project_id: projectId, idempotency_key: "key" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchImpl);

    render(<DocumentsWorkspace />);
    await waitFor(() => expect(screen.getByText("还没有文档。上传一份 PDF、Word、Markdown 或 TXT 后即可开始解析。")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("上传文档"), { target: { files: [new File(["内容"], "说明.md", { type: "text/markdown" })] } });
    await waitFor(() => expect(screen.getByText("说明.md")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "说明.md" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("任务已完成")).toBeInTheDocument(), { timeout: 3000 });
    expect(fetchImpl).toHaveBeenCalledWith(expect.stringContaining("/ingestion-jobs/job-1"), expect.anything());
  });
});
