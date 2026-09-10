import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../src/components/layout/app-shell";

const getFocusableElements = (container: HTMLElement) =>
  Array.from(
    container.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  );

describe("AppShell mobile navigation", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads the shared project context once for desktop and mobile shell regions", async () => {
    render(
      <AppShell>
        <p>内容</p>
      </AppShell>,
    );

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  });

  it("preserves project context on the shell brand link", () => {
    window.history.replaceState({}, "", "/?project=22222222-2222-4222-8222-222222222222");

    render(
      <AppShell>
        <p>内容</p>
      </AppShell>,
    );

    expect(screen.getByRole("link", { name: "RAG Eval Platform" })).toHaveAttribute(
      "href",
      "/?project=22222222-2222-4222-8222-222222222222",
    );
  });

  it("opens an accessible modal drawer, closes on Escape, and restores focus", () => {
    render(
      <AppShell>
        <p>内容</p>
      </AppShell>,
    );

    const trigger = screen.getByRole("button", { name: "打开导航菜单" });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby", "mobile-navigation-title");
    expect(screen.getByRole("heading", { name: "导航菜单" })).toBeVisible();
    expect(screen.getByRole("button", { name: /^关闭导航菜单$/ })).toHaveFocus();

    fireEvent.keyDown(screen.getByRole("button", { name: /^关闭导航菜单$/ }), {
      key: "Escape",
    });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("traps Tab focus within the open drawer and closes from its backdrop", () => {
    render(
      <AppShell>
        <p>内容</p>
      </AppShell>,
    );

    fireEvent.click(screen.getByRole("button", { name: "打开导航菜单" }));
    const dialog = screen.getByRole("dialog");
    const focusable = getFocusableElements(dialog);
    const first = focusable[0];
    const last = focusable.at(-1);

    expect(first).toBeDefined();
    expect(last).toBeDefined();

    last?.focus();
    fireEvent.keyDown(last as HTMLElement, { key: "Tab" });
    expect(first).toHaveFocus();

    first?.focus();
    fireEvent.keyDown(first as HTMLElement, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "关闭导航背景" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
