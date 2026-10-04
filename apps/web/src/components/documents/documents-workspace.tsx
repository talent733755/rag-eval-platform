"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { DataCard } from "@/components/ui/data-card";
import { DocumentDetailDrawer } from "@/components/documents/document-detail-drawer";
import { GenerateCandidatesDialog } from "@/components/documents/generate-candidates-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ProjectLink } from "@/components/ui/project-link";
import { StatusBadge, type StatusBadgeStatus } from "@/components/ui/status-badge";
import { createApiClient } from "@/lib/api/client";
import { documentsReducer, initialDocumentsState } from "@/lib/documents/reducer";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";

function statusFor(value?: string): StatusBadgeStatus {
  if (value === "succeeded") return "success";
  if (value === "failed") return "failed";
  if (value === "processing") return "info";
  return "neutral";
}

function statusLabel(value?: string): string {
  return ({ succeeded: "解析成功", failed: "解析失败", processing: "解析中", queued: "排队中" } as Record<string, string>)[value ?? ""] ?? "未知";
}

export function DocumentsWorkspace() {
  const search = useProjectSearch();
  const projectId = getProjectIdFromSearch(search);
  const [state, dispatch] = useReducer(documentsReducer, initialDocumentsState);
  const [query, setQuery] = useState("");
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [generateTarget, setGenerateTarget] = useState<{ documentId: string; versionId: string; name: string } | null>(null);
  const [generatedDataset, setGeneratedDataset] = useState<{ datasetId: string; name: string } | null>(null);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<Set<string>>(new Set());
  const [batchGenerateOpen, setBatchGenerateOpen] = useState(false);
  const [batchDatasetName, setBatchDatasetName] = useState("");
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const client = useMemo(() => createApiClient(), []);
  const refreshDocuments = useCallback(() => setRefreshNonce((current) => current + 1), []);
  const rows = state.items;
  const parsedRows = rows.filter((row) => row.latest_version?.parse_status === "succeeded" && row.latest_version.id);
  const selectedParsedRows = parsedRows.filter((row) => selectedDocumentIds.has(row.id));

  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    dispatch({ type: "list_started" });
    client
      .listDocuments(projectId, { query: query ? { q: query } : undefined, signal: controller.signal })
      .then((response) => {
        dispatch({
          type: "list_succeeded",
          items: response.items,
          summary: response.summary ?? { total: response.items.length },
          nextCursor: response.next_cursor ?? null,
        });
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        dispatch({ type: "list_failed", message: reason instanceof Error ? reason.message : "文档加载失败" });
      });
    return () => controller.abort();
  }, [client, projectId, query, refreshNonce]);

  if (!projectId) {
    return <EmptyState title="文档库" description="请先在顶部选择一个项目，再管理原始文档和解析版本。" actionLabel="返回工作台" actionHref="/" />;
  }
  const submitBatchGenerate = async () => {
    const name = batchDatasetName.trim();
    if (!name || selectedParsedRows.length === 0) return;
    setBatchBusy(true);
    setBatchError(null);
    try {
      const primary = selectedParsedRows[0];
      const job = await client.generateCandidateDataset(projectId, {
        document_version_id: primary.latest_version!.id!,
        document_version_ids: selectedParsedRows.map((row) => row.latest_version!.id!),
        dataset_name: name,
        capability_version: "candidate-generation-v1",
        prompt_version: "v1",
        seed: null,
        randomness: 1,
      });
      setGeneratedDataset({ datasetId: job.dataset_id, name });
      setBatchGenerateOpen(false);
      setSelectedDocumentIds(new Set());
      setBatchDatasetName("");
    } catch (reason: unknown) {
      setBatchError(reason instanceof Error ? reason.message : "批量生成请求失败");
    } finally {
      setBatchBusy(false);
    }
  };

  const toggleSelect = (documentId: string) => {
    setSelectedDocumentIds((current) => {
      const next = new Set(current);
      if (next.has(documentId)) next.delete(documentId); else next.add(documentId);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelectedDocumentIds((current) => {
      if (current.size === parsedRows.length) return new Set();
      return new Set(parsedRows.map((row) => row.id));
    });
  };

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    if (files.length > 20) {
      dispatch({ type: "upload_rejected", message: "一次最多上传 20 个文件。" });
      return;
    }
    dispatch({ type: "upload_started" });
    try {
      const result = await client.uploadDocuments(projectId, Array.from(files));
      for (const item of result.items) {
        if (item.response) {
          dispatch({ type: "job_associated", documentId: item.response.document.id, jobId: item.response.ingestion_job.id });
        }
      }
      dispatch({ type: "upload_finished", outcomes: result.items });
      const refreshed = await client.listDocuments(projectId, { query: query ? { q: query } : undefined });
      dispatch({
        type: "list_succeeded",
        items: refreshed.items,
        summary: refreshed.summary ?? { total: refreshed.items.length },
        nextCursor: refreshed.next_cursor ?? null,
      });
      if (inputRef.current) inputRef.current.value = "";
    } catch (reason: unknown) {
      dispatch({ type: "upload_failed", message: reason instanceof Error ? reason.message : "文件上传失败" });
    }
  };

  return (
    <div className="mx-auto max-w-screen-2xl space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-primary">资产管理</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">文档库</h1>
          <p className="mt-2 text-sm text-muted">管理原始文档、版本和可追溯的解析状态。</p>
        </div>
        <div className="flex items-center gap-3">
          {selectedParsedRows.length > 0 && (
            <button type="button" className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90" onClick={() => setBatchGenerateOpen(true)}>
              批量生成评测集（{selectedParsedRows.length}）
            </button>
          )}
          <label className="inline-flex cursor-pointer items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90">
            {state.uploadState === "uploading" ? "上传中…" : "上传文档"}
            <input ref={inputRef} className="sr-only" type="file" multiple accept=".pdf,.docx,.md,.markdown,.txt" disabled={state.uploadState === "uploading"} onChange={(event) => void handleFiles(event.target.files)} />
          </label>
        </div>
      </div>

      {state.uploadMessage && <p className={state.uploadState === "error" || state.uploadState === "partial" ? "text-sm text-danger-foreground" : "text-sm text-success-foreground"} role={state.uploadState === "error" ? "alert" : "status"}>{state.uploadMessage}</p>}
      {generatedDataset && (
        <p className="flex items-center gap-2 text-sm text-success-foreground" role="status">
          已加入生成队列：评测集「{generatedDataset.name}」。
          <ProjectLink href={`/review?dataset=${generatedDataset.datasetId}`} className="rounded-md border border-border px-3 py-1 text-sm font-medium text-text hover:border-primary hover:text-primary">去审核</ProjectLink>
        </p>
      )}

      {batchGenerateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => !batchBusy && setBatchGenerateOpen(false)}>
          <div role="dialog" aria-modal="true" aria-label="批量生成评测集" className="w-full max-w-md rounded-lg border border-border bg-surface p-6 shadow-xl" onClick={(event) => event.stopPropagation()}>
            <h2 className="text-lg font-semibold text-text">批量生成评测集</h2>
            <p className="mt-1 text-sm text-muted">把选中的 {selectedParsedRows.length} 个文档的解析块合并成一个评测集，自动造题。</p>
            <form className="mt-5 space-y-4" onSubmit={(event) => { event.preventDefault(); void submitBatchGenerate(); }}>
              <label className="block text-sm text-text">
                <span className="mb-1 block">评测集名称</span>
                <input className="w-full rounded-md border border-border bg-canvas px-3 py-2 text-text" value={batchDatasetName} onChange={(event) => setBatchDatasetName(event.target.value)} maxLength={255} aria-label="评测集名称" disabled={batchBusy} />
              </label>
              {batchError && <p className="text-sm text-danger-foreground" role="alert">{batchError}</p>}
              <div className="flex justify-end gap-2 border-t border-border pt-4">
                <button type="button" className="rounded-md border border-border px-4 py-2 text-sm text-text disabled:opacity-50" onClick={() => setBatchGenerateOpen(false)} disabled={batchBusy}>取消</button>
                <button type="submit" className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50" disabled={batchBusy || !batchDatasetName.trim()}>{batchBusy ? "提交中…" : "开始生成"}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      <section aria-label="文档统计" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <DataCard label="文档总数" value={state.summary.total ?? rows.length} supportingText="当前项目" />
        <DataCard label="解析成功" value={rows.filter((row) => row.latest_version?.parse_status === "succeeded").length} supportingText="可生成候选" />
        <DataCard label="解析中" value={rows.filter((row) => ["queued", "processing"].includes(row.latest_version?.parse_status ?? "")).length} supportingText="等待 Worker" />
        <DataCard label="解析失败" value={rows.filter((row) => row.latest_version?.parse_status === "failed").length} supportingText="需要重试" />
      </section>

      <section className="rounded-lg border border-border bg-surface p-4 shadow-sm shadow-slate-900/5" aria-labelledby="documents-table-heading">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h2 id="documents-table-heading" className="text-base font-semibold text-text">全部文档</h2>
          <label className="flex items-center gap-2 text-sm text-muted">
            <span>搜索</span>
            <input className="rounded-md border border-border bg-canvas px-3 py-2 text-text" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="文档名称" />
          </label>
        </div>
        {state.listState === "loading" && <p className="mt-6 text-sm text-muted" role="status">正在加载文档…</p>}
        {state.listState === "error" && <p className="mt-6 text-sm text-danger-foreground" role="alert">{state.error}</p>}
        {state.listState === "success" && rows.length === 0 && (
          <div className="mt-6 rounded-lg border border-dashed border-border bg-canvas px-6 py-10 text-center">
            <p className="text-sm font-medium text-text">还没有文档</p>
            <p className="mx-auto mt-2 max-w-md text-sm text-muted">
              这是第一步。上传你的知识库文档（PDF、Word、Markdown 或 TXT），系统会自动解析，之后就能生成评测集了。
            </p>
          </div>
        )}
        {rows.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-muted">
                <tr><th className="px-3 py-3" scope="col"><input type="checkbox" aria-label="全选" checked={selectedParsedRows.length === parsedRows.length && parsedRows.length > 0} onChange={toggleSelectAll} /></th><th className="px-3 py-3" scope="col">文档名称</th><th className="px-3 py-3" scope="col">类型</th><th className="px-3 py-3" scope="col">版本</th><th className="px-3 py-3" scope="col">解析状态</th><th className="px-3 py-3" scope="col">操作</th></tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((row) => (
                  <tr key={row.id}><td className="px-3 py-4"><input type="checkbox" aria-label={`选择 ${row.display_name}`} checked={selectedDocumentIds.has(row.id)} onChange={() => toggleSelect(row.id)} disabled={row.latest_version?.parse_status !== "succeeded" || !row.latest_version.id} /></td><th className="px-3 py-4 font-medium text-text" scope="row"><button type="button" className="text-left hover:text-primary" onClick={() => setSelectedDocumentId(row.id)}>{row.display_name}</button></th><td className="px-3 py-4 text-muted">{row.source_type.toUpperCase()}</td><td className="px-3 py-4 text-muted">v{row.latest_version?.version_number ?? "—"}</td><td className="px-3 py-4"><StatusBadge status={statusFor(row.latest_version?.parse_status)}>{statusLabel(row.latest_version?.parse_status)}</StatusBadge></td><td className="px-3 py-4">{row.latest_version?.parse_status === "succeeded" && row.latest_version.id ? <button type="button" className="rounded-md border border-border px-3 py-1.5 text-sm text-text hover:border-primary hover:text-primary" onClick={() => { setGeneratedDataset(null); setGenerateTarget({ documentId: row.id, versionId: row.latest_version!.id!, name: row.display_name }); }}>生成候选评测集</button> : <span className="text-xs text-muted">—</span>}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {selectedDocumentId && <DocumentDetailDrawer client={client} projectId={projectId} documentId={selectedDocumentId} jobId={state.jobsByDocument[selectedDocumentId]} onClose={() => setSelectedDocumentId(null)} onChanged={refreshDocuments} />}
      {generateTarget && <GenerateCandidatesDialog client={client} projectId={projectId} documentId={generateTarget.documentId} documentVersionId={generateTarget.versionId} documentName={generateTarget.name} onClose={() => setGenerateTarget(null)} onGenerated={(datasetId, name) => setGeneratedDataset({ datasetId, name })} />}
    </div>
  );
}
