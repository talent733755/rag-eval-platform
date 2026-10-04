import "@testing-library/jest-dom/vitest";

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardWorkspace } from "../src/components/dashboard/dashboard-workspace";

const projectId = "11111111-1111-4111-8111-111111111111";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("DashboardWorkspace guided flow", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", `/?project=${projectId}`);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("guides a brand-new project to upload documents first", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ items: [], next_cursor: null, summary: { total: 0 } })) // documents
      .mockResolvedValueOnce(jsonResponse([])) // datasets
      .mockResolvedValueOnce(jsonResponse([])) // experiments
      .mockResolvedValueOnce(jsonResponse([])); // adapters
    vi.stubGlobal("fetch", fetchImpl);

    render(<DashboardWorkspace />);

    await waitFor(() => expect(screen.getByText("四步完成一次 RAG 评测")).toBeInTheDocument());
    expect(await screen.findByText("当前步骤")).toBeInTheDocument();
    // Step 1 is current: its action is visible.
    expect(screen.getByRole("link", { name: "去上传文档" })).toBeInTheDocument();
    expect(screen.getByText("还没有文档")).toBeInTheDocument();
  });

  it("highlights review step once documents and a dataset exist", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          items: [
            {
              id: "d1",
              display_name: "doc.md",
              source_type: "markdown",
              latest_version: { id: "v1", version_number: 1, parse_status: "succeeded" },
            },
          ],
          next_cursor: null,
          summary: { total: 1 },
        }),
      )
      .mockResolvedValueOnce(jsonResponse([{ id: "ds1", name: "评测集A", status: "draft" }]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse([]));
    vi.stubGlobal("fetch", fetchImpl);

    render(<DashboardWorkspace />);

    // Review step should be current (docs parsed + dataset exist, nothing published).
    await waitFor(() => expect(screen.getByRole("link", { name: "去审核" })).toBeInTheDocument());
    expect(screen.getByText("1 个评测集")).toBeInTheDocument();
    expect(screen.getByText("还没有已发布版本")).toBeInTheDocument();
  });

  it("shows an empty-state guide when no project is selected", () => {
    window.history.replaceState({}, "", "/");
    render(<DashboardWorkspace />);
    expect(screen.getByText("欢迎使用 RAG 评测平台")).toBeInTheDocument();
  });
});
