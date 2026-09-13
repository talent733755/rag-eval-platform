"use client";

import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { createApiClient } from "@/lib/api/client";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";

export function TracesWorkspace() {
  const search = useProjectSearch();
  const projectId = getProjectIdFromSearch(search);
  const client = useMemo(() => createApiClient(), []);
  const [traces, setTraces] = useState<Awaited<ReturnType<typeof client.listTraces>>>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    void client.listTraces(projectId, { query: { limit: 100 }, signal: controller.signal }).then((result) => { setTraces(result); setState("ready"); }).catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === "AbortError")) setState("error"); });
    return () => controller.abort();
  }, [client, projectId]);

  if (!projectId) return <EmptyState title="Trace 诊断" description="请先选择一个项目，再查看评测链路。" actionLabel="返回工作台" actionHref="/" />;
  return <div className="mx-auto max-w-screen-2xl space-y-6"><div><p className="text-sm font-medium text-primary">可观测性</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">Trace 诊断</h1><p className="mt-2 text-sm text-muted">Trace 只展示脱敏后的阶段、哈希和安全 Blob 引用。</p></div>{state === "loading" && <p className="text-sm text-muted" role="status">正在加载 Trace…</p>}{state === "error" && <p className="text-sm text-danger-foreground" role="alert">Trace 加载失败，请稍后重试。</p>}{state === "ready" && traces.length === 0 && <EmptyState title="暂无 Trace" description="完成带 Trace 的实验项后，这里会出现可追溯的阶段记录。" actionLabel="查看实验" actionHref="/experiments" />}{traces.length > 0 && <section className="rounded-lg border border-border bg-surface p-4"><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="border-b border-border text-xs text-muted"><tr><th className="px-3 py-3" scope="col">Trace ID</th><th className="px-3 py-3" scope="col">级别</th><th className="px-3 py-3" scope="col">阶段</th><th className="px-3 py-3" scope="col">版本</th><th className="px-3 py-3" scope="col">时间</th></tr></thead><tbody className="divide-y divide-border">{traces.map((trace) => <tr key={trace.id}><th className="px-3 py-4 font-mono text-xs font-medium text-text" scope="row">{trace.trace_id}</th><td className="px-3 py-4"><StatusBadge status={trace.level === "full" ? "info" : "neutral"}>{trace.level}</StatusBadge></td><td className="px-3 py-4 text-muted">{trace.stages.map((stage) => String(stage.name)).join("、") || "—"}</td><td className="px-3 py-4 font-mono text-xs text-muted">{trace.trace_version}</td><td className="px-3 py-4 text-xs text-muted">{new Date(trace.created_at).toLocaleString("zh-CN")}</td></tr>)}</tbody></table></div></section>}</div>;
}
