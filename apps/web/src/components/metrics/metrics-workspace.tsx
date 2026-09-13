"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { DataCard } from "@/components/ui/data-card";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { createApiClient } from "@/lib/api/client";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";

type Api = ReturnType<typeof createApiClient>;
type Experiment = Awaited<ReturnType<Api["listExperiments"]>>[number];
type Metric = Awaited<ReturnType<Api["listExperimentMetrics"]>>[number];

function formatValue(metric: Metric): string {
  if (metric.value === null) return "缺失";
  if (metric.metric_key.includes("rate") || ["recall@5", "precision@5", "hit_rate@5", "mrr", "ndcg@5"].includes(metric.metric_key)) {
    return `${(metric.value * 100).toFixed(1)}%`;
  }
  return metric.value.toFixed(1);
}

function statusLabel(status: string): string {
  return { succeeded: "已完成", failed: "失败", cancelled: "已取消" }[status] ?? status;
}

export function MetricsWorkspace() {
  const search = useProjectSearch();
  const projectId = getProjectIdFromSearch(search);
  const client = useMemo(() => createApiClient(), []);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [recalculating, setRecalculating] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!projectId) return;
    setState("loading");
    try {
      const loadedExperiments = await client.listExperiments(projectId, { signal });
      setExperiments(loadedExperiments);
      const latest = loadedExperiments.find((experiment) => ["succeeded", "failed", "cancelled"].includes(experiment.status));
      setMetrics(latest ? await client.listExperimentMetrics(projectId, latest.id, { signal }) : []);
      setState("ready");
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(reason instanceof Error ? reason.message : "指标加载失败");
      setState("error");
    }
  }, [client, projectId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  if (!projectId) return <EmptyState title="指标看板" description="请先选择一个项目，再查看版本化评测指标。" actionLabel="返回工作台" actionHref="/" />;
  const activeProjectId = projectId;
  const latest = experiments.find((experiment) => ["succeeded", "failed", "cancelled"].includes(experiment.status));
  const aggregateMetrics = metrics.filter((metric) => metric.scope === "run");
  const latestRunId = aggregateMetrics[0]?.run_id;

  async function recalculate() {
    if (!latest || !latestRunId) return;
    setRecalculating(true);
    setError(null);
    try {
      setMetrics(await client.recalculateRunMetrics(activeProjectId, latest.id, latestRunId));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "指标重算失败");
    } finally {
      setRecalculating(false);
    }
  }

  return <div className="mx-auto max-w-screen-2xl space-y-6">
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div><p className="text-sm font-medium text-primary">质量验证</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">指标看板</h1><p className="mt-2 text-sm text-muted">只展示已持久化的 Run 结果；每个数值都带样本数、指标版本和计算时间。</p></div>
      {latest && <StatusBadge status={latest.status === "succeeded" ? "success" : latest.status === "failed" ? "failed" : "warning"}>{statusLabel(latest.status)}</StatusBadge>}
    </div>
    {error && <p className="text-sm text-danger-foreground" role="alert">{error}</p>}
    {state === "loading" && <p className="text-sm text-muted" role="status">正在加载指标…</p>}
    {state === "ready" && !latest && <EmptyState title="暂无已完成实验" description="启动并完成一次实验后，这里会展示工程、生成和检索指标。" actionLabel="创建实验" actionHref="/experiments" />}
    {latest && <>
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="最新 Run 指标">
        {aggregateMetrics.slice(0, 4).map((metric) => <DataCard key={metric.id} label={metric.metric_key} value={formatValue(metric)} supportingText={`n=${metric.sample_count} · ${metric.metric_version}`} />)}
      </section>
      <section className="rounded-lg border border-border bg-surface p-4" aria-labelledby="metric-results-heading">
        <div className="flex items-center justify-between gap-3"><div><h2 id="metric-results-heading" className="text-base font-semibold text-text">Run 指标结果</h2><p className="mt-1 text-xs text-muted">实验：{latest.name} · 计算时间以服务端 UTC 为准</p></div><button type="button" className="rounded-md border border-border px-3 py-2 text-xs text-text disabled:opacity-50" disabled={recalculating || !latestRunId} onClick={() => void recalculate()}>{recalculating ? "重算中…" : "幂等重算"}</button></div>
        {aggregateMetrics.length === 0 ? <p className="mt-6 text-sm text-muted">该 Run 尚未生成指标，可能需要重算或等待 Worker。</p> : <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[720px] text-left text-sm"><thead className="border-b border-border text-xs text-muted"><tr><th className="px-3 py-3" scope="col">指标</th><th className="px-3 py-3" scope="col">结果</th><th className="px-3 py-3" scope="col">样本数</th><th className="px-3 py-3" scope="col">版本</th><th className="px-3 py-3" scope="col">状态</th></tr></thead><tbody className="divide-y divide-border">{aggregateMetrics.map((metric) => <tr key={metric.id}><th className="px-3 py-3 font-medium text-text" scope="row">{metric.metric_key}</th><td className="px-3 py-3 text-text">{formatValue(metric)}{metric.missing_reason && <span className="ml-2 text-xs text-muted">({metric.missing_reason})</span>}</td><td className="px-3 py-3 text-muted">{metric.sample_count}</td><td className="px-3 py-3 font-mono text-xs text-muted">{metric.metric_version}</td><td className="px-3 py-3"><StatusBadge status={metric.value === null ? "warning" : "success"}>{metric.value === null ? "缺失" : "可用"}</StatusBadge></td></tr>)}</tbody></table></div>}
      </section>
    </>}
  </div>;
}
