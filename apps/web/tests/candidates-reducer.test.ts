import { describe, expect, it } from "vitest";

import { initialReviewState, reviewReducer } from "../src/lib/candidates/reducer";

describe("candidate review reducer", () => {
  it("updates only the item whose review request completed", () => {
    const state = {
      ...initialReviewState,
      items: [
        { id: "item-1", review_status: "pending" },
        { id: "item-2", review_status: "pending" },
      ],
      pendingItemIds: new Set(["item-1"]),
    };

    const next = reviewReducer(state, {
      type: "review_succeeded",
      item: { id: "item-1", review_status: "accepted" },
    });

    expect(next.items).toEqual([
      { id: "item-1", review_status: "accepted" },
      { id: "item-2", review_status: "pending" },
    ]);
    expect(next.pendingItemIds.has("item-1")).toBe(false);
  });

  it("locks review edits after publication", () => {
    const next = reviewReducer(initialReviewState, { type: "published" });

    expect(next.published).toBe(true);
    expect(next.pendingItemIds.size).toBe(0);
  });
});
