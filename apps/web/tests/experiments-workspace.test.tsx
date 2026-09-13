import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExperimentsWorkspace } from "../src/components/experiments/experiments-workspace";

const projectId = "11111111-1111-4111-8111-111111111111";
const datasetId = "22222222-2222-4222-8222-222222222222";
const versionId = "33333333-3333-4333-8333-333333333333";

describe("ExperimentsWorkspace", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads only published dataset versions and available dependencies", async () => {
    window.history.replaceState({}, "", `/experiments?project=${projectId}`);
    const fetchImpl = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: datasetId, name: "产品评测集", status: "published" }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "adapter-1", name: "线上 Adapter", enabled: true, last_test_status: "succeeded", adapter_version: "adapter-v1" }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "provider-1", name: "模型服务", enabled: true, model_name: "model-a" }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: versionId, dataset_id: datasetId, version_number: 2, status: "published", item_count: 3 }]), { status: 200 }));
    vi.stubGlobal("fetch", fetchImpl);

    render(<ExperimentsWorkspace />);

    await waitFor(() => expect(screen.getByText("创建实验草稿")).toBeInTheDocument());
    expect(screen.getByRole("option", { name: /产品评测集 · v2/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /线上 Adapter/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /模型服务/ })).toBeInTheDocument();
    expect(screen.getByText("还没有实验。创建一个草稿开始评测。")).toBeInTheDocument();
  });
});
