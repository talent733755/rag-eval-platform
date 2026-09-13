import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdaptersWorkspace } from "../src/components/adapters/adapters-workspace";

const projectId = "11111111-1111-4111-8111-111111111111";
const adapter = {
  id: "adapter-1",
  organization_id: "org-1",
  project_id: projectId,
  name: "初始 Adapter",
  kind: "http",
  endpoint: "https://adapter.example.test",
  credential_ref: null,
  token_last4: null,
  adapter_version: "adapter-v1",
  trace_level: "minimal",
  timeout_seconds: 30,
  retry_count: 0,
  enabled: false,
  last_test_status: "never",
  created_at: "2026-01-01T00:00:00Z",
};

describe("AdaptersWorkspace", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("edits, tests, and deletes an adapter", async () => {
    window.history.replaceState({}, "", `/adapters?project=${projectId}`);
    const updated = { ...adapter, name: "更新后的 Adapter" };
    const tested = { ...updated, last_test_status: "succeeded" };
    const fetchImpl = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify([adapter]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(updated), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([updated]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(tested), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchImpl);
    vi.stubGlobal("confirm", vi.fn(() => true));

    render(<AdaptersWorkspace />);
    await waitFor(() => expect(screen.getByText("初始 Adapter")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.change(screen.getByLabelText("Adapter 名称"), { target: { value: "更新后的 Adapter" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    await waitFor(() => expect(screen.getByText("更新后的 Adapter")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));
    await waitFor(() => expect(screen.getByText("已连接")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    await waitFor(() => expect(screen.getByText("还没有配置 Adapter。")).toBeInTheDocument());
    expect(fetchImpl).toHaveBeenCalledTimes(5);
  });
});
