import type { Permission } from "./auth/permissions";

export type NavigationItem = {
  label: string;
  href: string;
  permission: Permission;
};

export type NavigationGroup = {
  label: string;
  children: readonly NavigationItem[];
};

export type NavigationEntry = NavigationItem | NavigationGroup;

export const navigation = [
  { label: "工作台", href: "/", permission: "project.read" },
  {
    label: "数据资产",
    children: [
      { label: "文档库", href: "/documents", permission: "asset.read" },
      { label: "评测集", href: "/datasets", permission: "asset.read" },
      { label: "审核队列", href: "/review", permission: "asset.edit" },
    ],
  },
  {
    label: "评测实验",
    children: [
      { label: "Pipeline 接入", href: "/adapters", permission: "adapter.edit" },
      { label: "实验任务", href: "/experiments", permission: "experiment.edit" },
      { label: "运行记录", href: "/runs", permission: "experiment.read" },
    ],
  },
  {
    label: "分析诊断",
    children: [
      { label: "指标看板", href: "/metrics", permission: "diagnostics.read" },
      { label: "Trace 分析", href: "/traces", permission: "diagnostics.read" },
      { label: "失败案例", href: "/failures", permission: "diagnostics.read" },
    ],
  },
  {
    label: "系统管理",
    children: [
      { label: "模型与服务", href: "/settings/services", permission: "service.admin" },
      { label: "项目与成员", href: "/settings/members", permission: "member.admin" },
    ],
  },
] as const satisfies readonly NavigationEntry[];

export function isNavigationGroup(entry: NavigationEntry): entry is NavigationGroup {
  return "children" in entry;
}

export function isNavigationItemActive(pathname: string | null, href: string): boolean {
  const currentPathname = pathname ?? "/";
  if (href === "/") {
    return currentPathname === "/";
  }

  return currentPathname === href || currentPathname.startsWith(`${href}/`);
}
