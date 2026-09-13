"use client";

import { useEffect, useState } from "react";

import type { createApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated";

type Api = ReturnType<typeof createApiClient>;
type Document = components["schemas"]["DocumentResponse"];

type DocumentDetailDrawerProps = {
  client: Api;
  projectId: string;
  documentId: string;
  jobId?: string;
  onClose: () => void;
  onChanged: () => void;
};

export function DocumentDetailDrawer({ client, projectId, documentId, jobId, onClose, onChanged }: DocumentDetailDrawerProps) {
  const [document, setDocument] = useState<Document | null>(null);
  const [job, setJob] = useState<Awaited<ReturnType<Api["getIngestionJob"]>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    client
      .getDocument(projectId, documentId, { signal: controller.signal })
      .then(setDocument)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "文档详情加载失败");
      });
    return () => controller.abort();
  }, [client, documentId, projectId]);

  useEffect(() => {
    if (!jobId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = 500;
    const poll = () => {
      client
        .getIngestionJob(projectId, jobId, { signal: controller.signal })
        .then((result) => {
          setJob(result);
          if (!["succeeded", "failed", "cancelled"].includes(result.status)) {
            delay = Math.min(delay * 2, 5000);
            timer = setTimeout(poll, delay);
          } else {
            onChanged();
          }
        })
        .catch((reason: unknown) => {
          if (reason instanceof DOMException && reason.name === "AbortError") return;
          setError(reason instanceof Error ? reason.message : "任务状态加载失败");
        });
    };
    poll();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [client, jobId, onChanged, projectId]);

  async function archive() {
    setBusy(true);
    setError(null);
    try {
      await client.archiveDocument(projectId, documentId, false);
      onChanged();
      onClose();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "文档归档失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-20 flex justify-end bg-slate-950/30" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className="h-full w-full max-w-xl overflow-y-auto bg-surface p-6 shadow-xl" aria-label="文档详情" role="dialog" aria-modal="true">
        <div className="flex items-center justify-between gap-4"><h2 className="text-lg font-semibold text-text">文档详情</h2><button type="button" className="rounded-md border border-border px-3 py-1.5 text-sm text-muted" onClick={onClose}>关闭</button></div>
        {error && <p className="mt-4 text-sm text-danger-foreground" role="alert">{error}</p>}
        {!document && !error && <p className="mt-6 text-sm text-muted" role="status">正在加载详情…</p>}
        {document && <div className="mt-6 space-y-5"><div><p className="text-xs text-muted">文件名</p><p className="mt-1 font-medium text-text">{document.display_name}</p></div><div className="grid grid-cols-2 gap-4"><div><p className="text-xs text-muted">类型</p><p className="mt-1 text-sm text-text">{document.source_type.toUpperCase()}</p></div><div><p className="text-xs text-muted">最新版本</p><p className="mt-1 text-sm text-text">v{document.latest_version?.version_number ?? "—"}</p></div></div>{job && <div className="rounded-md border border-border bg-canvas p-4" aria-live="polite"><p className="text-xs text-muted">解析任务</p><p className="mt-1 text-sm font-medium text-text">{job.status === "succeeded" ? "任务已完成" : job.status === "failed" ? "任务失败" : job.status === "cancelled" ? "任务已取消" : "任务处理中"}</p>{job.last_error_code && <p className="mt-2 text-xs text-danger-foreground">失败码：{job.last_error_code}</p>}<div className="mt-3 flex gap-2">{job.status === "failed" && document.latest_version && <button type="button" className="rounded-md border border-border px-3 py-1.5 text-sm text-text disabled:opacity-50" disabled={busy} onClick={async () => { setBusy(true); try { const retried = await client.retryParse(projectId, documentId, document.latest_version?.id ?? ""); setJob(retried); onChanged(); } catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "重试失败"); } finally { setBusy(false); } }}>重试解析</button>}{["queued", "processing"].includes(job.status) && <button type="button" className="rounded-md border border-danger px-3 py-1.5 text-sm text-danger-foreground disabled:opacity-50" disabled={busy} onClick={async () => { setBusy(true); try { setJob(await client.cancelIngestionJob(projectId, job.id)); } catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "取消失败"); } finally { setBusy(false); } }}>取消任务</button>}</div></div>}{document.latest_version && <div className="rounded-md border border-border bg-canvas p-4"><p className="text-xs text-muted">解析状态</p><p className="mt-1 text-sm font-medium text-text">{document.latest_version.parse_status}</p><p className="mt-4 text-xs text-muted">SHA-256</p><p className="mt-1 break-all font-mono text-xs text-text">{document.latest_version.sha256}</p><p className="mt-4 text-xs text-muted">解析器版本</p><p className="mt-1 text-sm text-text">{document.latest_version.parser_version ?? "—"}</p>{document.latest_version.parse_error_code && <p className="mt-4 text-sm text-danger-foreground">失败码：{document.latest_version.parse_error_code}</p>}</div>}<div className="flex gap-2 border-t border-border pt-5"><button type="button" className="rounded-md border border-danger px-3 py-1.5 text-sm text-danger-foreground disabled:opacity-50" disabled={busy || Boolean(document.archived_at)} onClick={() => void archive()}>归档文档</button></div></div>}
      </aside>
    </div>
  );
}
