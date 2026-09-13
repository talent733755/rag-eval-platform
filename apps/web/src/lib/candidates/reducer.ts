export type ReviewItem = {
  id: string;
  review_status: string;
  [key: string]: unknown;
};

export type ReviewState = {
  items: ReviewItem[];
  pendingItemIds: Set<string>;
  published: boolean;
  error: string | null;
};

export const initialReviewState: ReviewState = {
  items: [],
  pendingItemIds: new Set(),
  published: false,
  error: null,
};

export type ReviewAction =
  | { type: "items_loaded"; items: ReviewItem[] }
  | { type: "review_started"; itemId: string }
  | { type: "review_succeeded"; item: ReviewItem }
  | { type: "review_failed"; itemId: string; message: string }
  | { type: "published" };

export function reviewReducer(state: ReviewState, action: ReviewAction): ReviewState {
  switch (action.type) {
    case "items_loaded":
      return { ...state, items: action.items, error: null };
    case "review_started":
      return {
        ...state,
        error: null,
        pendingItemIds: new Set(state.pendingItemIds).add(action.itemId),
      };
    case "review_succeeded":
      return {
        ...state,
        items: state.items.map((item) => (item.id === action.item.id ? action.item : item)),
        pendingItemIds: without(state.pendingItemIds, action.item.id),
        error: null,
      };
    case "review_failed":
      return {
        ...state,
        pendingItemIds: without(state.pendingItemIds, action.itemId),
        error: action.message,
      };
    case "published":
      return { ...state, published: true, pendingItemIds: new Set(), error: null };
  }
}

function without(values: Set<string>, value: string): Set<string> {
  const next = new Set(values);
  next.delete(value);
  return next;
}
