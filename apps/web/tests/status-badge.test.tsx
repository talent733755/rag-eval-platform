import "@testing-library/jest-dom/vitest";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StatusBadge } from "../src/components/ui/status-badge";
import { designTokens } from "../src/lib/design-tokens";

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

  it.each([
    ["success", "successForeground", "#166534"],
    ["warning", "warningForeground", "#92400E"],
    ["danger", "dangerForeground", "#991B1B"],
  ] as const)("uses an accessible foreground token for %s", (status, token, value) => {
    render(<StatusBadge status={status}>状态</StatusBadge>);

    expect(screen.getByRole("status")).toHaveClass(`text-${status}-foreground`);
    expect(designTokens.light[token]).toBe(value);
  });
});
