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
});
