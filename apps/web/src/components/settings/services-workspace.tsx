"use client";

import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { createApiClient } from "@/lib/api/client";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";

export function ServicesWorkspace() {
  const search = useProjectSearch();
  const projectId = getProjectIdFromSearch(search);
  const client = useMemo(() => createApiClient(), []);
  const [providers, setProviders] = useState<Awaited<ReturnType<typeof client.listModelProviders>>>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    void client.listModelProviders(projectId, { signal: controller.signal }).then((result) => { setProviders(result); setState("ready"); }).catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === "AbortError")) setState("error"); });
    return () => controller.abort();
  }, [client, projectId]);

  if (!projectId) return <EmptyState title="模型与服务" description="请先选择一个项目，再查看模型服务配置。" actionLabel="返回工作台" actionHref="/" />;
  return <div className="mx-auto max-w-screen-2xl space-y-6"><div><p className="text-sm font-medium text-primary">项目设置</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">模型与服务</h1><p className="mt-2 text-sm text-muted">凭据只通过安全引用注入，页面和 API 不返回明文密钥。</p></div>{state === "loading" && <p className="text-sm text-muted" role="status">正在加载服务…</p>}{state === "error" && <p className="text-sm text-danger-foreground" role="alert">服务加载失败，请稍后重试。</p>}{state === "ready" && providers.length === 0 && <EmptyState title="暂无模型服务" description="请在 API 中配置模型 Provider 后再启动实验。" actionLabel="查看实验" actionHref="/experiments" />}{providers.length > 0 && <section className="rounded-lg border border-border bg-surface p-4"><div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-sm"><thead className="border-b border-border text-xs text-muted"><tr><th className="px-3 py-3" scope="col">名称</th><th className="px-3 py-3" scope="col">模型</th><th className="px-3 py-3" scope="col">状态</th><th className="px-3 py-3" scope="col">凭据引用</th></tr></thead><tbody className="divide-y divide-border">{providers.map((provider) => <tr key={provider.id}><th className="px-3 py-4 font-medium text-text" scope="row">{provider.name}</th><td className="px-3 py-4 text-muted">{provider.model_name}</td><td className="px-3 py-4"><StatusBadge status={provider.enabled ? "success" : "neutral"}>{provider.enabled ? "已启用" : "已停用"}</StatusBadge></td><td className="px-3 py-4 font-mono text-xs text-muted">{provider.credential_ref}</td></tr>)}</tbody></table></div></section>}</div>;
}
