"use client";

import { useState } from "react";

import type { createApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated";

type Api = ReturnType<typeof createApiClient>;
type Job = components["schemas"]["DocumentJobResponse"];
type Document = components["schemas"]["DocumentResponse"];

type IngestionJobStatusProps = {
  client: Api;
  projectId: string;
  documentId: string;
  document: Document;
  job: Job;
  onChanged: () => void;
};

function statusLabel(status: string): string {
  return (
    {
      succeeded: "任务已完成",
      failed: "任务失败",
      cancelled: "任务已取消",
    } as Record<string, string>
  )[status] ?? "任务处理中";
}

export function IngestionJobStatus({ client, projectId, documentId, document, job, onChanged }: IngestionJobStatusProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentJob, setCurrentJob] = useState<Job>(job);

  async function retry() {
    if (!document.latest_version) return;
    setBusy(true);
    setError(null);
    try {
      setCurrentJob(await client.retryParse(projectId, documentId, document.latest_version.id));
      onChanged();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "重试失败");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    setError(null);
    try {
      setCurrentJob(await client.cancelIngestionJob(projectId, currentJob.id));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "取消失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-md border border-border bg-canvas p-4" aria-live="polite">
      <p className="text-xs text-muted">解析任务</p>
      <p className="mt-1 text-sm font-medium text-text">{statusLabel(currentJob.status)}</p>
      {currentJob.last_error_code && <p className="mt-2 text-xs text-danger-foreground">失败码：{currentJob.last_error_code}</p>}
      {error && <p className="mt-2 text-xs text-danger-foreground" role="alert">{error}</p>}
      <div className="mt-3 flex gap-2">
        {currentJob.status === "failed" && document.latest_version && (
          <button type="button" className="rounded-md border border-border px-3 py-1.5 text-sm text-text disabled:opacity-50" disabled={busy} onClick={() => void retry()}>
            重试解析
          </button>
        )}
        {["queued", "processing"].includes(currentJob.status) && (
          <button type="button" className="rounded-md border border-danger px-3 py-1.5 text-sm text-danger-foreground disabled:opacity-50" disabled={busy} onClick={() => void cancel()}>
            取消任务
          </button>
        )}
      </div>
    </div>
  );
}
