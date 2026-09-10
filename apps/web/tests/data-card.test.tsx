import "@testing-library/jest-dom/vitest";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DataCard } from "../src/components/ui/data-card";

describe("DataCard trends", () => {
  afterEach(() => cleanup());

  it.each([
    ["up", "趋势上升", "text-success-foreground"],
    ["down", "趋势下降", "text-danger-foreground"],
    ["neutral", "趋势持平", "text-muted"],
  ] as const)("renders a non-color marker and accessible text for %s", (direction, label, textClass) => {
    render(
      <DataCard
        label="质量"
        value="94%"
        trend={{ direction, value: "+4%", label: "较上次" }}
      />,
    );

    const trend = screen.getByTestId(`data-card-trend-${direction}`);
    expect(trend).toHaveClass(textClass);
    expect(trend).toHaveTextContent("+4%");
    expect(screen.getByText(label, { selector: ".sr-only" })).toBeInTheDocument();
    const marker = trend.querySelector("[data-trend-marker]");
    expect(marker).not.toBeNull();
    expect(marker?.getAttribute("aria-hidden")).toBe("true");
  });
});
