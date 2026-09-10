import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectSwitcher } from "../src/components/layout/project-switcher";
import { SidebarNav } from "../src/components/layout/sidebar-nav";
import { UserMenu } from "../src/components/layout/user-menu";
import { EmptyState } from "../src/components/ui/empty-state";
import { hasPermission } from "../src/lib/auth/permissions";

const projects = [
  {
    id: "11111111-1111-4111-8111-111111111111",
    name: "Alpha 项目",
  },
  {
    id: "22222222-2222-4222-8222-222222222222",
    name: "Beta 项目",
  },
];

describe("permission-aware navigation", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows approved menu groups and links in canonical order", () => {
    render(<SidebarNav role="admin" pathname="/" />);

    const navigation = screen.getByRole("navigation", { name: "主导航" });
    expect(navigation.textContent).toContain("工作台");
    expect(navigation.textContent).toContain("数据资产");
    expect(navigation.textContent).toContain("评测实验");
    expect(navigation.textContent).toContain("分析诊断");
    expect(navigation.textContent).toContain("系统管理");

    expect([...navigation.querySelectorAll("a")].map((link) => link.textContent)).toEqual([
      "工作台",
      "文档库",
      "评测集",
      "审核队列",
      "Pipeline 接入",
      "实验任务",
      "运行记录",
      "指标看板",
      "Trace 分析",
      "失败案例",
      "模型与服务",
      "项目与成员",
    ]);
  });

  it("filters links by role permissions", () => {
    render(<SidebarNav role="viewer" pathname="/settings/members" />);

    expect(screen.getByRole("link", { name: "工作台" })).toBeVisible();
    expect(screen.getByRole("link", { name: "文档库" })).toBeVisible();
    expect(screen.getByRole("link", { name: "运行记录" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "审核队列" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Pipeline 接入" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "实验任务" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "项目与成员" })).not.toBeInTheDocument();
    expect(screen.queryByText("系统管理")).not.toBeInTheDocument();
  });

  it("keeps service administration exclusive to administrators", () => {
    expect(hasPermission("admin", "service.admin")).toBe(true);
    expect(hasPermission("editor", "service.admin")).toBe(false);
    expect(hasPermission("viewer", "service.admin")).toBe(false);

    const { unmount } = render(<SidebarNav role="editor" pathname="/settings/services" />);
    expect(screen.queryByRole("link", { name: "模型与服务" })).not.toBeInTheDocument();
    unmount();

    render(<SidebarNav role="admin" pathname="/settings/services" />);
    expect(screen.getByRole("link", { name: "模型与服务" })).toBeVisible();
  });

  it("marks the exact or nested pathname as the active accessible link", () => {
    render(<SidebarNav role="admin" pathname="/settings/members/invite" />);

    expect(screen.getByRole("link", { name: "项目与成员" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "工作台" })).not.toHaveAttribute("aria-current");
  });

  it("preserves project B after switching from project A on sidebar and empty-state links", async () => {
    window.history.replaceState({}, "", `/?project=${projects[0].id}`);
    vi.stubGlobal("fetch", vi.fn());
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(projects), { status: 200 }));

    render(
      <>
        <ProjectSwitcher />
        <SidebarNav role="admin" pathname="/" />
        <EmptyState title="文档库" description="desc" actionLabel="前往评测集" actionHref="/datasets" />
      </>,
    );

    const switcher = await screen.findByRole("combobox", { name: "当前项目" });
    fireEvent.change(switcher, { target: { value: projects[1].id } });

    await waitFor(() => {
      expect(screen.getByRole("link", { name: "文档库" })).toHaveAttribute(
        "href",
        `/documents?project=${projects[1].id}`,
      );
      expect(screen.getByRole("link", { name: "前往评测集" })).toHaveAttribute(
        "href",
        `/datasets?project=${projects[1].id}`,
      );
    });
  });
});

describe("project switcher", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    window.history.replaceState({}, "", "/");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows loading and then the projects returned by the API", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(projects), { status: 200, headers: { "content-type": "application/json" } }),
    );

    render(<ProjectSwitcher />);

    expect(screen.getByRole("status")).toHaveTextContent("正在加载项目");
    expect(await screen.findByRole("combobox", { name: "当前项目" })).toHaveValue(projects[0].id);
    expect(screen.getByRole("option", { name: "Alpha 项目" })).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("preserves a valid query selection and updates it when changed", async () => {
    window.history.replaceState({}, "", `/?project=${projects[1].id}`);
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(projects), { status: 200 }));

    render(<ProjectSwitcher />);

    const select = await screen.findByRole("combobox", { name: "当前项目" });
    expect(select).toHaveValue(projects[1].id);

    fireEvent.change(select, { target: { value: projects[0].id } });
    expect(new URL(window.location.href).searchParams.get("project")).toBe(projects[0].id);
  });

  it("shows an explicit error and does not fall back after a failed load", async () => {
    window.history.replaceState({}, "", `/?project=${projects[1].id}`);
    vi.mocked(fetch).mockRejectedValue(new Error("network unavailable"));

    render(<ProjectSwitcher />);

    expect(await screen.findByRole("alert")).toHaveTextContent("项目加载失败");
    expect(screen.queryByRole("combobox", { name: "当前项目" })).not.toBeInTheDocument();
    expect(window.location.search).toContain(projects[1].id);
  });

  it("shows an explicit empty state when the actor has no projects", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("[]", { status: 200 }));

    render(<ProjectSwitcher />);

    expect(await screen.findByRole("status")).toHaveTextContent("暂无可用项目");
    expect(screen.queryByRole("combobox", { name: "当前项目" })).not.toBeInTheDocument();
  });

  it("shows an error instead of silently dropping malformed API entries", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify([projects[0], { id: projects[1].id }]), { status: 200 }),
    );

    render(<ProjectSwitcher />);

    expect(await screen.findByRole("alert")).toHaveTextContent("项目加载失败");
    expect(screen.queryByRole("combobox", { name: "当前项目" })).not.toBeInTheDocument();
  });

  it("does not select the first project when the query project is unavailable", async () => {
    window.history.replaceState({}, "", `/?project=33333333-3333-4333-8333-333333333333`);
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(projects), { status: 200 }));

    render(<ProjectSwitcher />);

    expect(await screen.findByRole("status")).toHaveTextContent("当前项目不可用");
    expect(screen.queryByRole("combobox", { name: "当前项目" })).not.toBeInTheDocument();
    expect(window.location.search).toContain("33333333-3333-4333-8333-333333333333");
  });

  it("does not update state or URL after unmounting during a successful response", async () => {
    let resolveResponse: (response: Response) => void = () => undefined;
    vi.mocked(fetch).mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveResponse = resolve;
      }),
    );
    const replaceState = vi.spyOn(window.history, "replaceState");

    const { unmount } = render(<ProjectSwitcher />);
    unmount();
    resolveResponse(new Response(JSON.stringify(projects), { status: 200 }));
    await Promise.resolve();
    await Promise.resolve();

    expect(replaceState).not.toHaveBeenCalled();
  });
});

describe("user menu popover", () => {
  afterEach(() => cleanup());

  it("uses popover semantics and closes on Escape", () => {
    render(<UserMenu />);

    const trigger = screen.getByRole("button", { name: "打开用户菜单" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    fireEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "用户菜单" })).toBeVisible();
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "用户菜单" })).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });
});
