import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectSwitcher } from "../src/components/layout/project-switcher";
import { SidebarNav } from "../src/components/layout/sidebar-nav";

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
  afterEach(() => cleanup());

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

  it("marks the exact or nested pathname as the active accessible link", () => {
    render(<SidebarNav role="admin" pathname="/settings/members/invite" />);

    expect(screen.getByRole("link", { name: "项目与成员" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "工作台" })).not.toHaveAttribute("aria-current");
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

  it("does not select the first project when the query project is unavailable", async () => {
    window.history.replaceState({}, "", `/?project=33333333-3333-4333-8333-333333333333`);
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(projects), { status: 200 }));

    render(<ProjectSwitcher />);

    expect(await screen.findByRole("status")).toHaveTextContent("当前项目不可用");
    expect(screen.queryByRole("combobox", { name: "当前项目" })).not.toBeInTheDocument();
    expect(window.location.search).toContain("33333333-3333-4333-8333-333333333333");
  });
});
