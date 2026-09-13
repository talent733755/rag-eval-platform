"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { createApiClient } from "@/lib/api/client";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";

type Api = ReturnType<typeof createApiClient>;
type Dataset = Awaited<ReturnType<Api["listCandidateDatasets"]>>[number];
type DatasetVersion = Awaited<ReturnType<Api["listCandidateDatasetVersions"]>>[number];
type Adapter = Awaited<ReturnType<Api["listAdapters"]>>[number];
type Provider = Awaited<ReturnType<Api["listModelProviders"]>>[number];
type Experiment = Awaited<ReturnType<Api["listExperiments"]>>[number];

type VersionChoice = { dataset: Dataset; version: DatasetVersion };

function statusLabel(status: string): string {
  return { draft: "草稿", queued: "排队中", running: "运行中", cancelling: "取消中", succeeded: "已完成", failed: "失败", cancelled: "已取消" }[status] ?? status;
}

function statusKind(status: string): "success" | "info" | "warning" | "failed" | "neutral" {
  if (status === "succeeded") return "success";
  if (["queued", "running"].includes(status)) return "info";
  if (status === "failed") return "failed";
  if (status === "cancelling") return "warning";
  return "neutral";
}

export function ExperimentsWorkspace() {
  const search = useProjectSearch();
  const projectId = getProjectIdFromSearch(search);
  const client = useMemo(() => createApiClient(), []);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [versions, setVersions] = useState<VersionChoice[]>([]);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [name, setName] = useState("");
  const [datasetVersionId, setDatasetVersionId] = useState("");
  const [adapterId, setAdapterId] = useState("");
  const [providerId, setProviderId] = useState("");
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runIds, setRunIds] = useState<Record<string, string>>({});

  const refreshExperiments = useCallback(async (signal?: AbortSignal) => {
    if (!projectId) return;
    const result = await client.listExperiments(projectId, { signal });
    setExperiments(result);
  }, [client, projectId]);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!projectId) return;
    setState("loading");
    try {
      const [datasets, loadedAdapters, loadedProviders, loadedExperiments] = await Promise.all([
        client.listCandidateDatasets(projectId, { signal }),
        client.listAdapters(projectId, { signal }),
        client.listModelProviders(projectId, { signal }),
        client.listExperiments(projectId, { signal }),
      ]);
      const loadedVersions = (await Promise.all(datasets.map(async (dataset) => ({ dataset, versions: await client.listCandidateDatasetVersions(projectId, dataset.id, { signal }) })))).flatMap(({ dataset, versions: datasetVersions }) => datasetVersions.map((version) => ({ dataset, version })));
      setVersions(loadedVersions);
      setAdapters(loadedAdapters);
      setProviders(loadedProviders);
      setExperiments(loadedExperiments);
      setDatasetVersionId((current) => current || loadedVersions.find(({ version }) => version.status === "published")?.version.id || "");
      setAdapterId((current) => current || loadedAdapters.find((adapter) => adapter.enabled && adapter.last_test_status === "succeeded")?.id || "");
      setProviderId((current) => current || loadedProviders.find((provider) => provider.enabled)?.id || "");
      setState("ready");
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(reason instanceof Error ? reason.message : "实验加载失败");
      setState("error");
    }
  }, [client, projectId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    if (!projectId || !experiments.some((experiment) => ["queued", "running", "cancelling"].includes(experiment.status))) return;
    const timer = window.setInterval(() => void refreshExperiments(), 3000);
    return () => window.clearInterval(timer);
  }, [experiments, projectId, refreshExperiments]);

  if (!projectId) return <EmptyState title="实验任务" description="请先选择一个项目，再创建可复现的评测实验。" actionLabel="返回工作台" actionHref="/" />;
  const activeProjectId = projectId;

  async function create() {
    if (!name.trim() || !datasetVersionId || !adapterId || !providerId) return;
    setBusyId("create");
    setError(null);
    try {
      await client.createExperiment(activeProjectId, { name: name.trim(), dataset_version_id: datasetVersionId, adapter_config_id: adapterId, model_provider_id: providerId, metric_versions: { retrieval: "v1" }, parameters: {}, random_seed: 42 });
      setName("");
      await load();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "实验创建失败");
    } finally {
      setBusyId(null);
    }
  }

  async function start(experiment: Experiment) {
    setBusyId(experiment.id);
    setError(null);
    try {
      const result = await client.startExperiment(activeProjectId, experiment.id);
      setRunIds((current) => ({ ...current, [experiment.id]: result.run.id }));
      setExperiments((current) => current.map((item) => item.id === result.experiment.id ? result.experiment : item));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "实验启动失败");
    } finally {
      setBusyId(null);
    }
  }

  async function cancel(experiment: Experiment) {
    const runId = runIds[experiment.id];
    if (!runId) return;
    setBusyId(experiment.id);
    setError(null);
    try {
      await client.cancelExperimentRun(activeProjectId, runId);
      await refreshExperiments();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "取消实验失败");
    } finally {
      setBusyId(null);
    }
  }

  return <div className="mx-auto max-w-screen-2xl space-y-6">
    <div><p className="text-sm font-medium text-primary">质量验证</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">实验任务</h1><p className="mt-2 text-sm text-muted">实验创建后固定评测集、Adapter、模型、指标版本、参数和随机种子；运行结果由独立 Worker 写入。</p></div>
    {error && <p className="text-sm text-danger-foreground" role="alert">{error}</p>}
    <section className="rounded-lg border border-border bg-surface p-4" aria-labelledby="experiment-create-heading"><h2 id="experiment-create-heading" className="text-base font-semibold text-text">创建实验草稿</h2><div className="mt-4 grid gap-3 md:grid-cols-4"><input className="rounded-md border border-border bg-canvas px-3 py-2 text-text" aria-label="实验名称" value={name} onChange={(event) => setName(event.target.value)} placeholder="实验名称" /><select className="rounded-md border border-border bg-canvas px-3 py-2 text-text" aria-label="评测集版本" value={datasetVersionId} onChange={(event) => setDatasetVersionId(event.target.value)}><option value="">选择已发布评测集版本</option>{versions.filter(({ version }) => version.status === "published").map(({ dataset, version }) => <option key={version.id} value={version.id}>{dataset.name} · v{version.version_number}（{version.item_count} 条）</option>)}</select><select className="rounded-md border border-border bg-canvas px-3 py-2 text-text" aria-label="Adapter" value={adapterId} onChange={(event) => setAdapterId(event.target.value)}><option value="">选择可用 Adapter</option>{adapters.filter((adapter) => adapter.enabled && adapter.last_test_status === "succeeded").map((adapter) => <option key={adapter.id} value={adapter.id}>{adapter.name} · {adapter.adapter_version}</option>)}</select><div className="flex gap-2"><select className="min-w-0 flex-1 rounded-md border border-border bg-canvas px-3 py-2 text-text" aria-label="模型服务" value={providerId} onChange={(event) => setProviderId(event.target.value)}><option value="">选择已启用模型</option>{providers.filter((provider) => provider.enabled).map((provider) => <option key={provider.id} value={provider.id}>{provider.name} · {provider.model_name}</option>)}</select><button type="button" className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50" disabled={busyId === "create" || !name.trim() || !datasetVersionId || !adapterId || !providerId} onClick={() => void create()}>创建</button></div></div></section>
    <section className="rounded-lg border border-border bg-surface p-4" aria-labelledby="experiment-list-heading"><h2 id="experiment-list-heading" className="text-base font-semibold text-text">实验列表</h2>{state === "loading" && <p className="mt-6 text-sm text-muted" role="status">正在加载…</p>}{state === "ready" && experiments.length === 0 && <p className="mt-6 text-sm text-muted">还没有实验。创建一个草稿开始评测。</p>}{experiments.length > 0 && <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[880px] text-left text-sm"><thead className="border-b border-border text-xs text-muted"><tr><th className="px-3 py-3" scope="col">名称</th><th className="px-3 py-3" scope="col">状态</th><th className="px-3 py-3" scope="col">进度</th><th className="px-3 py-3" scope="col">随机种子</th><th className="px-3 py-3" scope="col">操作</th></tr></thead><tbody className="divide-y divide-border">{experiments.map((experiment) => <tr key={experiment.id}><th className="px-3 py-4 font-medium text-text" scope="row">{experiment.name}</th><td className="px-3 py-4"><StatusBadge status={statusKind(experiment.status)}>{statusLabel(experiment.status)}</StatusBadge></td><td className="px-3 py-4 text-muted">{experiment.completed_units} / {experiment.total_units}</td><td className="px-3 py-4 font-mono text-xs text-muted">{experiment.random_seed}</td><td className="px-3 py-4"><div className="flex gap-2">{experiment.status === "draft" && <button type="button" className="rounded-md border border-border px-2 py-1 text-xs text-text disabled:opacity-50" disabled={busyId === experiment.id} onClick={() => void start(experiment)}>启动</button>}{["queued", "running", "cancelling"].includes(experiment.status) && <button type="button" className="rounded-md border border-danger px-2 py-1 text-xs text-danger-foreground disabled:opacity-50" disabled={busyId === experiment.id || experiment.status === "cancelling"} onClick={() => void cancel(experiment)}>取消</button>}{runIds[experiment.id] && <span className="py-1 text-xs text-muted">Run {runIds[experiment.id].slice(0, 8)}</span>}</div></td></tr>)}</tbody></table></div>}</section>
  </div>;
}
