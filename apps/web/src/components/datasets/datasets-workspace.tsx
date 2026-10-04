"use client";

import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { ProjectLink } from "@/components/ui/project-link";
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
  const [archivingId, setArchivingId] = useState<string | null>(null);

  async function archive(dataset: Dataset) {
    if (!projectId || archivingId) return;
    setArchivingId(dataset.id);
    setError(null);
    try {
      await client.archiveCandidateDataset(projectId, dataset.id);
      setDatasets((current) => current.filter((item) => item.id !== dataset.id));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "归档失败");
    } finally {
      setArchivingId(null);
    }
  }

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
        <p className="mt-2 text-sm text-muted">评测集是自动生成的候选样例，需逐条审核后发布，才能用于实验。</p>
      </div>
      <section className="rounded-lg border border-border bg-surface p-4 shadow-sm shadow-slate-900/5" aria-labelledby="datasets-heading">
        <h2 id="datasets-heading" className="text-base font-semibold text-text">评测集列表</h2>
        {state === "loading" && <p className="mt-6 text-sm text-muted" role="status">正在加载评测集…</p>}
        {state === "error" && <p className="mt-6 text-sm text-danger-foreground" role="alert">{error}</p>}
        {state === "success" && datasets.length === 0 && (
          <div className="mt-6 rounded-lg border border-dashed border-border bg-canvas px-6 py-10 text-center">
            <p className="text-sm font-medium text-text">还没有评测集</p>
            <p className="mt-2 text-sm text-muted">评测集由文档自动生成。请先到文档库上传文档并生成候选评测集。</p>
            <ProjectLink href="/documents" className="mt-4 inline-flex rounded-md bg-primary px-4 py-2 text-sm font-medium text-white">去上传文档</ProjectLink>
          </div>
        )}
        {datasets.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-muted">
                <tr><th className="px-3 py-3" scope="col">名称</th><th className="px-3 py-3" scope="col">状态</th><th className="px-3 py-3" scope="col">更新时间</th><th className="px-3 py-3" scope="col">操作</th></tr>
              </thead>
              <tbody className="divide-y divide-border">
                {datasets.map((dataset) => {
                  const status = statusMap[dataset.status] ?? { label: "未知", status: "neutral" as const };
                  return <tr key={dataset.id}><th scope="row" className="px-3 py-4 font-medium text-text">{dataset.name}</th><td className="px-3 py-4"><StatusBadge status={status.status}>{status.label}</StatusBadge></td><td className="px-3 py-4 text-muted">{new Date(dataset.updated_at).toLocaleString("zh-CN")}</td><td className="px-3 py-4"><div className="flex items-center gap-2"><ProjectLink href={`/review?dataset=${dataset.id}`} className="rounded-md border border-border px-3 py-1.5 text-sm text-text hover:border-primary hover:text-primary">去审核</ProjectLink><button type="button" disabled={archivingId === dataset.id} onClick={() => void archive(dataset)} className="rounded-md border border-border px-3 py-1.5 text-sm text-muted hover:border-danger hover:text-danger-foreground disabled:opacity-50">{archivingId === dataset.id ? "归档中…" : "归档"}</button></div></td></tr>;
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
