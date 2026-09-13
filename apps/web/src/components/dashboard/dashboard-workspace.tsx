"use client";

import { useEffect, useMemo, useState } from "react";

import { DataCard } from "@/components/ui/data-card";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { createApiClient } from "@/lib/api/client";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";

export function DashboardWorkspace() {
  const search = useProjectSearch();
  const projectId = getProjectIdFromSearch(search);
  const client = useMemo(() => createApiClient(), []);
  const [experimentCount, setExperimentCount] = useState(0);
  const [metricValues, setMetricValues] = useState<Record<string, number | null>>({});
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const experiments = await client.listExperiments(projectId, { signal: controller.signal });
        setExperimentCount(experiments.length);
        const latest = experiments.find((experiment) => experiment.status === "succeeded");
        if (latest) {
          const metrics = await client.listExperimentMetrics(projectId, latest.id, { signal: controller.signal });
          setMetricValues(Object.fromEntries(metrics.filter((metric) => metric.scope === "run").map((metric) => [metric.metric_key, metric.value])));
        }
        setState("ready");
      } catch (reason: unknown) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setState("error");
      }
    })();
    return () => controller.abort();
  }, [client, projectId]);

  if (!projectId) return <EmptyState title="评测工作台" description="请先选择一个项目，查看实验和质量指标。" actionLabel="进入实验" actionHref="/experiments" />;
  const percentage = (key: string): string => {
    const value = metricValues[key];
    return value === undefined || value === null ? "—" : `${(value * 100).toFixed(1)}%`;
  };

  return <div className="mx-auto max-w-screen-2xl space-y-6">
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-sm font-medium text-primary">工作台</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">评测工作台</h1><p className="mt-2 max-w-2xl text-sm text-muted">从已完成 Run 的版本化结果快速了解当前项目质量。</p></div><StatusBadge status={state === "error" ? "failed" : state === "loading" ? "info" : "success"}>{state === "error" ? "数据加载失败" : state === "loading" ? "加载中" : "数据已同步"}</StatusBadge></div>
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="项目概览"><DataCard label="成功率" value={percentage("success_rate")} supportingText="最新完成 Run" /><DataCard label="非空答案率" value={percentage("answer_nonempty_rate")} supportingText="生成质量" /><DataCard label="累计实验" value={experimentCount} supportingText="项目范围" /><DataCard label="Trace 覆盖率" value={percentage("trace_coverage")} supportingText="可诊断样例" /></section>
    <section className="rounded-lg border border-border bg-surface p-6" aria-labelledby="next-heading"><h2 id="next-heading" className="text-base font-semibold text-text">继续工作</h2><p className="mt-2 max-w-2xl text-sm text-muted">先准备已发布评测集、通过连接测试的 Adapter 和已启用模型，再启动实验。</p><a className="mt-4 inline-flex rounded-md bg-primary px-4 py-2 text-sm font-medium text-white" href="/experiments">查看实验</a></section>
  </div>;
}
