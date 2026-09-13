"use client";

import { useEffect, useMemo, useReducer, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { createApiClient } from "@/lib/api/client";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";
import { initialReviewState, reviewReducer, type ReviewItem } from "@/lib/candidates/reducer";

type Api = ReturnType<typeof createApiClient>;
type Dataset = Awaited<ReturnType<Api["listCandidateDatasets"]>>[number];
type Version = Awaited<ReturnType<Api["listCandidateDatasetVersions"]>>[number];
type Item = Awaited<ReturnType<Api["listCandidateItems"]>>[number];

export function CandidateReviewWorkspace() {
  const projectSearch = useProjectSearch();
  const projectId = getProjectIdFromSearch(projectSearch);
  const client = useMemo(() => createApiClient(), []);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [state, dispatch] = useReducer(reviewReducer, initialReviewState);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    client
      .listCandidateDatasets(projectId, { signal: controller.signal })
      .then((result) => {
        setDatasets(result);
        setDatasetId((current) => current || result[0]?.id || "");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        dispatch({ type: "review_failed", itemId: "", message: reason instanceof Error ? reason.message : "评测集加载失败" });
      });
    return () => controller.abort();
  }, [client, projectId]);

  useEffect(() => {
    if (!projectId || !datasetId) return;
    const controller = new AbortController();
    setLoading(true);
    client
      .listCandidateDatasetVersions(projectId, datasetId, { signal: controller.signal })
      .then((result) => {
        setVersions(result);
        setVersionId((current) => current || result[0]?.id || "");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        dispatch({ type: "review_failed", itemId: "", message: reason instanceof Error ? reason.message : "评测集版本加载失败" });
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [client, datasetId, projectId]);

  useEffect(() => {
    if (!projectId || !datasetId || !versionId) return;
    const controller = new AbortController();
    setLoading(true);
    client
      .listCandidateItems(projectId, datasetId, versionId, { signal: controller.signal })
      .then((result) => dispatch({ type: "items_loaded", items: result as Item[] as ReviewItem[] }))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        dispatch({ type: "review_failed", itemId: "", message: reason instanceof Error ? reason.message : "候选加载失败" });
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [client, datasetId, projectId, versionId]);

  if (!projectId) {
    return <EmptyState title="审核队列" description="请先选择一个项目，再审核自动生成的候选。" actionLabel="返回工作台" actionHref="/" />;
  }
  const activeProjectId = projectId;

  const selectedVersion = versions.find((version) => version.id === versionId);
  const isPublished = state.published || selectedVersion?.status === "published";

  async function review(item: Item, reviewStatus: "accepted" | "rejected") {
    if (isPublished) return;
    dispatch({ type: "review_started", itemId: item.id });
    try {
      const updated = await client.reviewCandidateItem(activeProjectId, datasetId, versionId, {
        item_id: item.id,
        review_status: reviewStatus,
        comment: null,
      });
      dispatch({ type: "review_succeeded", item: updated as Item as ReviewItem });
    } catch (reason: unknown) {
      dispatch({ type: "review_failed", itemId: item.id, message: reason instanceof Error ? reason.message : "审核保存失败" });
    }
  }

  async function publish() {
    if (isPublished || state.pendingItemIds.size > 0 || state.items.some((item) => item.review_status === "pending")) return;
    try {
      await client.publishCandidateDatasetVersion(activeProjectId, datasetId, versionId);
      dispatch({ type: "published" });
    } catch (reason: unknown) {
      dispatch({ type: "review_failed", itemId: "", message: reason instanceof Error ? reason.message : "发布失败" });
    }
  }

  return (
    <div className="mx-auto max-w-screen-2xl space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-primary">质量门禁</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">审核队列</h1>
          <p className="mt-2 text-sm text-muted">逐条确认候选和来源证据；已发布版本不可修改。</p>
        </div>
        <button type="button" className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={isPublished || state.items.length === 0 || state.items.some((item) => item.review_status === "pending")} onClick={() => void publish()}>
          {isPublished ? "已发布" : "发布版本"}
        </button>
      </div>
      {state.error && <p className="text-sm text-danger-foreground" role="alert">{state.error}</p>}
      <section className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4 sm:flex-row" aria-label="审核范围">
        <label className="flex flex-1 flex-col gap-1 text-sm text-muted">评测集<select className="rounded-md border border-border bg-canvas px-3 py-2 text-text" value={datasetId} onChange={(event) => { setDatasetId(event.target.value); setVersionId(""); }}><option value="">请选择评测集</option>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}</select></label>
        <label className="flex flex-1 flex-col gap-1 text-sm text-muted">版本<select className="rounded-md border border-border bg-canvas px-3 py-2 text-text" value={versionId} onChange={(event) => setVersionId(event.target.value)}><option value="">请选择版本</option>{versions.map((version) => <option key={version.id} value={version.id}>v{version.version_number} · {version.status}</option>)}</select></label>
      </section>
      {loading && <p className="text-sm text-muted" role="status">正在加载候选…</p>}
      {!loading && versionId && state.items.length === 0 && <p className="text-sm text-muted">当前版本没有候选，或候选任务尚未完成。</p>}
      <div className="grid gap-4 xl:grid-cols-2">
        {state.items.map((rawItem) => {
          const item = rawItem as unknown as Item;
          const busy = state.pendingItemIds.has(item.id);
          return <article key={item.id} className="rounded-lg border border-border bg-surface p-5 shadow-sm shadow-slate-900/5"><div className="flex items-start justify-between gap-4"><h2 className="font-semibold text-text">{item.question}</h2><StatusBadge status={item.review_status === "accepted" ? "success" : item.review_status === "rejected" ? "failed" : "warning"}>{item.review_status === "accepted" ? "已接受" : item.review_status === "rejected" ? "已拒绝" : "待审核"}</StatusBadge></div><p className="mt-3 text-sm text-muted">参考答案：{item.reference_answer}</p><p className="mt-2 text-xs text-muted">来源版本：{item.source_version_id} · 置信度：{item.confidence}</p><div className="mt-4 space-y-2 border-t border-border pt-3">{item.evidence.map((evidence) => <p key={evidence.id} className="text-xs text-muted">证据 chunk {evidence.ordinal}：{evidence.excerpt ?? "（无摘录）"}</p>)}</div><div className="mt-4 flex gap-2"><button type="button" className="rounded-md border border-success px-3 py-1.5 text-sm text-success-foreground disabled:opacity-50" disabled={isPublished || busy} onClick={() => void review(item, "accepted")}>接受</button><button type="button" className="rounded-md border border-danger px-3 py-1.5 text-sm text-danger-foreground disabled:opacity-50" disabled={isPublished || busy} onClick={() => void review(item, "rejected")}>拒绝</button></div></article>;
        })}
      </div>
      {selectedVersion && <p className="text-xs text-muted">当前版本 v{selectedVersion.version_number}，共 {state.items.length} 条候选。</p>}
    </div>
  );
}
