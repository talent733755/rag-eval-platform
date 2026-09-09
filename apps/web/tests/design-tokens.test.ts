import { describe, expect, it } from "vitest";

import { designTokens } from "../src/lib/design-tokens";

describe("design token parity", () => {
  it("keeps the same semantic color token names in light and dark themes", () => {
    expect(Object.keys(designTokens.light).sort()).toEqual(Object.keys(designTokens.dark).sort());
  });

  it("keeps the elevated surface and primary soft values aligned with CSS", () => {
    expect(designTokens.light.surfaceElevated).toBe("#FFFFFF");
    expect(designTokens.dark.primarySoft).toBe("#172033");
    expect(designTokens.light.focus).toBe("#1D4ED8");
    expect(designTokens.dark.focus).toBe("#BFDBFE");
  });
});
