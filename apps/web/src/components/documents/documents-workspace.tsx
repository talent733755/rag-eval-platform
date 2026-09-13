"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { DataCard } from "@/components/ui/data-card";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge, type StatusBadgeStatus } from "@/components/ui/status-badge";
import { createApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";

type DocumentRow = components["schemas"]["DocumentResponse"];

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
  const [rows, setRows] = useState<DocumentRow[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({ total: 0 });
  const [query, setQuery] = useState("");
  const [state, setState] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [uploadState, setUploadState] = useState<"idle" | "uploading" | "success" | "error">("idle");
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const client = useMemo(() => createApiClient(), []);

  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    setState("loading");
    setError(null);
    client
      .listDocuments(projectId, { query: query ? { q: query } : undefined, signal: controller.signal })
      .then((response) => {
        setRows(response.items);
        setSummary(response.summary ?? { total: response.items.length });
        setState("success");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "文档加载失败");
        setState("error");
      });
    return () => controller.abort();
  }, [client, projectId, query, refreshNonce]);

  if (!projectId) {
    return <EmptyState title="文档库" description="请先在顶部选择一个项目，再管理原始文档和解析版本。" actionLabel="返回工作台" actionHref="/" />;
  }
  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    if (files.length > 20) {
      setUploadState("error");
      setUploadMessage("一次最多上传 20 个文件。");
      return;
    }
    setUploadState("uploading");
    setUploadMessage(null);
    try {
      const result = await client.uploadDocuments(projectId, Array.from(files));
      const failed = result.items.filter((item) => item.status === "failed");
      setUploadState(failed.length ? "error" : "success");
      setUploadMessage(failed.length ? `${failed.length} 个文件上传失败，请查看详情。` : `已提交 ${result.items.length} 个文件，解析任务已排队。`);
      if (inputRef.current) inputRef.current.value = "";
      setRefreshNonce((current) => current + 1);
    } catch (reason: unknown) {
      setUploadState("error");
      setUploadMessage(reason instanceof Error ? reason.message : "文件上传失败");
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
          {uploadState === "uploading" ? "上传中…" : "上传文档"}
          <input ref={inputRef} className="sr-only" type="file" multiple accept=".pdf,.docx,.md,.markdown,.txt" disabled={uploadState === "uploading"} onChange={(event) => void handleFiles(event.target.files)} />
        </label>
      </div>

      {uploadMessage && <p className={uploadState === "error" ? "text-sm text-danger-foreground" : "text-sm text-success-foreground"} role={uploadState === "error" ? "alert" : "status"}>{uploadMessage}</p>}

      <section aria-label="文档统计" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <DataCard label="文档总数" value={summary.total ?? rows.length} supportingText="当前项目" />
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
        {state === "loading" && <p className="mt-6 text-sm text-muted" role="status">正在加载文档…</p>}
        {state === "error" && <p className="mt-6 text-sm text-danger-foreground" role="alert">{error}</p>}
        {state === "success" && rows.length === 0 && <p className="mt-6 text-sm text-muted">还没有文档。上传一份 PDF、Word、Markdown 或 TXT 后即可开始解析。</p>}
        {rows.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-muted">
                <tr><th className="px-3 py-3" scope="col">文档名称</th><th className="px-3 py-3" scope="col">类型</th><th className="px-3 py-3" scope="col">版本</th><th className="px-3 py-3" scope="col">解析状态</th></tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((row) => (
                  <tr key={row.id}><th className="px-3 py-4 font-medium text-text" scope="row">{row.display_name}</th><td className="px-3 py-4 text-muted">{row.source_type.toUpperCase()}</td><td className="px-3 py-4 text-muted">v{row.latest_version?.version_number ?? "—"}</td><td className="px-3 py-4"><StatusBadge status={statusFor(row.latest_version?.parse_status)}>{statusLabel(row.latest_version?.parse_status)}</StatusBadge></td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
