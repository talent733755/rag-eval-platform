import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CandidateReviewWorkspace } from "../src/components/candidates/candidate-review-workspace";

const projectId = "11111111-1111-4111-8111-111111111111";
const datasetId = "22222222-2222-4222-8222-222222222222";
const versionId = "33333333-3333-4333-8333-333333333333";

describe("CandidateReviewWorkspace", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads candidates, saves one review, and publishes only after it is accepted", async () => {
    window.history.replaceState({}, "", `/review?project=${projectId}`);
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: datasetId, name: "产品评测集", status: "draft", updated_at: "2026-01-01T00:00:00Z" }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: versionId, dataset_id: datasetId, version_number: 1, status: "review", item_count: 1 }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "item-1", question: "问题", reference_answer: "答案", source_version_id: "version-1", confidence: 0.9, review_status: "pending", evidence: [{ id: "evidence-1", ordinal: 0, excerpt: "原文" }] }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "item-1", question: "问题", reference_answer: "答案", source_version_id: "version-1", confidence: 0.9, review_status: "accepted", evidence: [{ id: "evidence-1", ordinal: 0, excerpt: "原文" }] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: versionId, version_number: 1, status: "published" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchImpl);

    render(<CandidateReviewWorkspace />);

    await waitFor(() => expect(screen.getByText("问题")).toBeInTheDocument());
    expect(screen.getByText("待审核")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "接受" }));
    await waitFor(() => expect(screen.getByText("已接受")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "发布版本" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "已发布" })).toBeInTheDocument());
    expect(fetchImpl).toHaveBeenCalledTimes(5);
  });
});
