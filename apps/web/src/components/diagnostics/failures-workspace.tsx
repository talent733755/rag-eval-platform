"use client";

import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { createApiClient } from "@/lib/api/client";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";

export function FailuresWorkspace() {
  const search = useProjectSearch();
  const projectId = getProjectIdFromSearch(search);
  const client = useMemo(() => createApiClient(), []);
  const [failures, setFailures] = useState<Awaited<ReturnType<typeof client.listFailures>>>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    void client.listFailures(projectId, { query: { limit: 100 }, signal: controller.signal }).then((result) => { setFailures(result); setState("ready"); }).catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === "AbortError")) setState("error"); });
    return () => controller.abort();
  }, [client, projectId]);

  if (!projectId) return <EmptyState title="失败案例" description="请先选择一个项目，再查看失败分类和重试建议。" actionLabel="返回工作台" actionHref="/" />;
  return <div className="mx-auto max-w-screen-2xl space-y-6"><div><p className="text-sm font-medium text-primary">可观测性</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">失败案例</h1><p className="mt-2 text-sm text-muted">失败原因经过稳定分类和脱敏，只保留支持排障的安全上下文。</p></div>{state === "loading" && <p className="text-sm text-muted" role="status">正在加载失败案例…</p>}{state === "error" && <p className="text-sm text-danger-foreground" role="alert">失败案例加载失败，请稍后重试。</p>}{state === "ready" && failures.length === 0 && <EmptyState title="暂无失败案例" description="失败的实验项会按超时、Adapter 错误等稳定分类记录。" actionLabel="查看实验" actionHref="/experiments" />}{failures.length > 0 && <section className="rounded-lg border border-border bg-surface p-4"><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="border-b border-border text-xs text-muted"><tr><th className="px-3 py-3" scope="col">分类</th><th className="px-3 py-3" scope="col">说明</th><th className="px-3 py-3" scope="col">重试</th><th className="px-3 py-3" scope="col">Attempt</th><th className="px-3 py-3" scope="col">Trace</th></tr></thead><tbody className="divide-y divide-border">{failures.map((failure) => <tr key={failure.id}><th className="px-3 py-4 font-medium text-text" scope="row">{failure.code}</th><td className="px-3 py-4 text-muted">{failure.safe_message}</td><td className="px-3 py-4"><StatusBadge status={failure.retryable ? "warning" : "neutral"}>{failure.retryable ? "可重试" : "建议排查"}</StatusBadge></td><td className="px-3 py-4 text-muted">{failure.attempt_number}</td><td className="px-3 py-4 font-mono text-xs text-muted">{failure.trace_id ?? "—"}</td></tr>)}</tbody></table></div></section>}</div>;
}
