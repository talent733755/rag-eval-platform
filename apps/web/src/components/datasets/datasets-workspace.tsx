"use client";

import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge, type StatusBadgeStatus } from "@/components/ui/status-badge";
import { createApiClient } from "@/lib/api/client";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";

type Dataset = Awaited<ReturnType<ReturnType<typeof createApiClient>["listCandidateDatasets"]>>[number];

const statusMap: Record<string, { label: string; status: StatusBadgeStatus }> = {
  draft: { label: "草稿", status: "neutral" },
  review: { label: "审核中", status: "warning" },
  published: { label: "已发布", status: "success" },
  archived: { label: "已归档", status: "neutral" },
};

export function DatasetsWorkspace() {
  const search = useProjectSearch();
  const projectId = getProjectIdFromSearch(search);
  const client = useMemo(() => createApiClient(), []);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [state, setState] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    setState("loading");
    setError(null);
    client
      .listCandidateDatasets(projectId, { signal: controller.signal })
      .then((result) => {
        setDatasets(result);
        setState("success");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "评测集加载失败");
        setState("error");
      });
    return () => controller.abort();
  }, [client, projectId]);

  if (!projectId) {
    return <EmptyState title="评测集" description="请先在顶部选择一个项目，再查看候选评测集版本和审核状态。" actionLabel="返回工作台" actionHref="/" />;
  }

  return (
    <div className="mx-auto max-w-screen-2xl space-y-6">
      <div>
        <p className="text-sm font-medium text-primary">质量资产</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">评测集</h1>
        <p className="mt-2 text-sm text-muted">候选样例必须经过逐条审核，发布后的版本不可原地修改。</p>
      </div>
      <section className="rounded-lg border border-border bg-surface p-4 shadow-sm shadow-slate-900/5" aria-labelledby="datasets-heading">
        <h2 id="datasets-heading" className="text-base font-semibold text-text">候选评测集</h2>
        {state === "loading" && <p className="mt-6 text-sm text-muted" role="status">正在加载评测集…</p>}
        {state === "error" && <p className="mt-6 text-sm text-danger-foreground" role="alert">{error}</p>}
        {state === "success" && datasets.length === 0 && <p className="mt-6 text-sm text-muted">当前项目还没有候选评测集。</p>}
        {datasets.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-muted">
                <tr><th className="px-3 py-3" scope="col">名称</th><th className="px-3 py-3" scope="col">状态</th><th className="px-3 py-3" scope="col">更新时间</th></tr>
              </thead>
              <tbody className="divide-y divide-border">
                {datasets.map((dataset) => {
                  const status = statusMap[dataset.status] ?? { label: "未知", status: "neutral" as const };
                  return <tr key={dataset.id}><th scope="row" className="px-3 py-4 font-medium text-text">{dataset.name}</th><td className="px-3 py-4"><StatusBadge status={status.status}>{status.label}</StatusBadge></td><td className="px-3 py-4 text-muted">{new Date(dataset.updated_at).toLocaleString("zh-CN")}</td></tr>;
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
