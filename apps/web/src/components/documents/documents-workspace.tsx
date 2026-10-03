"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { DataCard } from "@/components/ui/data-card";
import { DocumentDetailDrawer } from "@/components/documents/document-detail-drawer";
import { GenerateCandidatesDialog } from "@/components/documents/generate-candidates-dialog";
import { EmptyState } from "@/components/ui/empty-state";
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
  const [generateMessage, setGenerateMessage] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const client = useMemo(() => createApiClient(), []);
  const refreshDocuments = useCallback(() => setRefreshNonce((current) => current + 1), []);
  const rows = state.items;

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
        <label className="inline-flex cursor-pointer items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90">
          {state.uploadState === "uploading" ? "上传中…" : "上传文档"}
          <input ref={inputRef} className="sr-only" type="file" multiple accept=".pdf,.docx,.md,.markdown,.txt" disabled={state.uploadState === "uploading"} onChange={(event) => void handleFiles(event.target.files)} />
        </label>
      </div>

      {state.uploadMessage && <p className={state.uploadState === "error" || state.uploadState === "partial" ? "text-sm text-danger-foreground" : "text-sm text-success-foreground"} role={state.uploadState === "error" ? "alert" : "status"}>{state.uploadMessage}</p>}
      {generateMessage && <p className="text-sm text-success-foreground" role="status">{generateMessage}</p>}

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
        {state.listState === "success" && rows.length === 0 && <p className="mt-6 text-sm text-muted">还没有文档。上传一份 PDF、Word、Markdown 或 TXT 后即可开始解析。</p>}
        {rows.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-muted">
                <tr><th className="px-3 py-3" scope="col">文档名称</th><th className="px-3 py-3" scope="col">类型</th><th className="px-3 py-3" scope="col">版本</th><th className="px-3 py-3" scope="col">解析状态</th><th className="px-3 py-3" scope="col">操作</th></tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((row) => (
                  <tr key={row.id}><th className="px-3 py-4 font-medium text-text" scope="row"><button type="button" className="text-left hover:text-primary" onClick={() => setSelectedDocumentId(row.id)}>{row.display_name}</button></th><td className="px-3 py-4 text-muted">{row.source_type.toUpperCase()}</td><td className="px-3 py-4 text-muted">v{row.latest_version?.version_number ?? "—"}</td><td className="px-3 py-4"><StatusBadge status={statusFor(row.latest_version?.parse_status)}>{statusLabel(row.latest_version?.parse_status)}</StatusBadge></td><td className="px-3 py-4">{row.latest_version?.parse_status === "succeeded" && row.latest_version.id ? <button type="button" className="rounded-md border border-border px-3 py-1.5 text-sm text-text hover:border-primary hover:text-primary" onClick={() => { setGenerateMessage(null); setGenerateTarget({ documentId: row.id, versionId: row.latest_version!.id!, name: row.display_name }); }}>生成候选评测集</button> : <span className="text-xs text-muted">—</span>}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {selectedDocumentId && <DocumentDetailDrawer client={client} projectId={projectId} documentId={selectedDocumentId} jobId={state.jobsByDocument[selectedDocumentId]} onClose={() => setSelectedDocumentId(null)} onChanged={refreshDocuments} />}
      {generateTarget && <GenerateCandidatesDialog client={client} projectId={projectId} documentId={generateTarget.documentId} documentVersionId={generateTarget.versionId} documentName={generateTarget.name} onClose={() => setGenerateTarget(null)} onGenerated={setGenerateMessage} />}
    </div>
  );
}
