import "@testing-library/jest-dom/vitest";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StatusBadge } from "../src/components/ui/status-badge";

describe("StatusBadge", () => {
  afterEach(() => cleanup());

  it.each([
    ["success", "解析成功"],
    ["warning", "处理中"],
    ["danger", "解析失败"],
  ] as const)("renders %s text and status semantics", (status, text) => {
    render(<StatusBadge status={status}>{text}</StatusBadge>);

    expect(screen.getByText(text)).toBeVisible();
    expect(screen.getByRole("status")).toHaveAttribute("data-status", status);
  });

  it("renders failure text and status semantics for the failed alias", () => {
    render(<StatusBadge status="failed">解析失败</StatusBadge>);

    expect(screen.getByText("解析失败")).toBeVisible();
    expect(screen.getByRole("status")).toHaveAttribute("data-status", "failed");
  });
});
