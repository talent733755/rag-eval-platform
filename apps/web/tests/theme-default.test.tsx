import "@testing-library/jest-dom/vitest";

import { describe, expect, it } from "vitest";

import RootLayout from "../src/app/layout";

describe("root theme", () => {
  it("explicitly defaults the document to the light theme", () => {
    const root = RootLayout({
      children: <p>内容</p>,
    });

    expect(root.props["data-theme"]).toBe("light");
  });
});
